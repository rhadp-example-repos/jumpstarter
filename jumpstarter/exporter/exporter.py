from jumpstarter.v1 import (
    jumpstarter_pb2,
    jumpstarter_pb2_grpc,
    router_pb2,
    router_pb2_grpc,
)
from jumpstarter.common import Metadata
from jumpstarter.drivers import DriverBase, Session
from jumpstarter.drivers.composite import Composite
from uuid import UUID, uuid4
from dataclasses import dataclass, asdict, is_dataclass
from google.protobuf import struct_pb2, json_format
from typing import List
from collections import ChainMap
import itertools
import anyio


@dataclass(kw_only=True)
class ExporterSession:
    session: Session
    devices: List[DriverBase]
    mapping: dict[UUID, DriverBase]

    def __init__(self, devices_factory):
        self.session = Session()
        self.devices = devices_factory(self.session)
        self.mapping = {}

        def subdevices(device):
            if isinstance(device, Composite):
                return dict(
                    ChainMap(*[subdevices(subdevice) for subdevice in device.devices])
                )
            else:
                return {device.uuid: device}

        for device in self.devices:
            self.mapping |= subdevices(device)


@dataclass(kw_only=True)
class Exporter(
    jumpstarter_pb2_grpc.ExporterServiceServicer,
    router_pb2_grpc.RouterServiceServicer,
    Metadata,
):
    session: ExporterSession

    def add_to_server(self, server):
        jumpstarter_pb2_grpc.add_ExporterServiceServicer_to_server(self, server)
        router_pb2_grpc.add_RouterServiceServicer_to_server(self, server)

    async def GetReport(self, request, context):
        return jumpstarter_pb2.GetReportResponse(
            uuid=str(self.uuid),
            labels=self.labels,
            device_report=itertools.chain(
                *[device.reports() for device in self.session.devices]
            ),
        )

    async def DriverCall(self, request, context):
        args = [json_format.MessageToDict(arg) for arg in request.args]
        result = await self.session.mapping[UUID(request.device_uuid)].call(
            request.driver_method, args
        )
        return jumpstarter_pb2.DriverCallResponse(
            call_uuid=str(uuid4()),
            result=json_format.ParseDict(
                asdict(result) if is_dataclass(result) else result, struct_pb2.Value()
            ),
        )

    async def StreamingDriverCall(self, request, context):
        args = [json_format.MessageToDict(arg) for arg in request.args]
        async for result in self.session.mapping[
            UUID(request.device_uuid)
        ].streaming_call(request.driver_method, args):
            yield jumpstarter_pb2.StreamingDriverCallResponse(
                call_uuid=str(uuid4()),
                result=json_format.ParseDict(
                    asdict(result) if is_dataclass(result) else result,
                    struct_pb2.Value(),
                ),
            )

    async def Stream(self, request_iterator, context):
        async def forward(stream):
            async with anyio.create_task_group() as tg:

                async def rx():
                    try:
                        async for frame in request_iterator:
                            await stream.send(frame.payload)
                    except anyio.BrokenResourceError:
                        pass
                    finally:
                        await stream.send_eof()

                tg.start_soon(rx)

                try:
                    async for payload in stream:
                        yield router_pb2.StreamResponse(payload=payload)
                except anyio.BrokenResourceError:
                    pass

        stream_id = ""

        for key, value in context.invocation_metadata():
            # device connection
            if key == "device":
                async with self.session.mapping[UUID(value)].connect() as stream:
                    async for v in forward(stream):
                        yield v
                return
            if key == "stream_id":
                stream_id = value

        # exporter connection
        client_to_exporter_tx, client_to_exporter_rx = (
            anyio.create_memory_object_stream[bytes](32)
        )
        exporter_to_client_tx, exporter_to_client_rx = (
            anyio.create_memory_object_stream[bytes](32)
        )
        to_client = anyio.streams.stapled.StapledObjectStream(
            client_to_exporter_tx, exporter_to_client_rx
        )
        to_exporter = anyio.streams.stapled.StapledObjectStream(
            exporter_to_client_tx, client_to_exporter_rx
        )

        self.session.session.conns[UUID(stream_id)] = to_exporter

        async for v in forward(to_client):
            yield v
