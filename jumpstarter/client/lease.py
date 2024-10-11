import logging
from contextlib import AbstractAsyncContextManager, AbstractContextManager, asynccontextmanager, contextmanager
from dataclasses import dataclass, field

import grpc
from anyio import create_task_group, create_unix_listener, fail_after, sleep
from anyio.from_thread import BlockingPortal
from google.protobuf import duration_pb2
from grpc.aio import Channel

from jumpstarter.client import client_from_channel
from jumpstarter.common import MetadataFilter, TemporarySocket
from jumpstarter.common.condition import condition_false, condition_true
from jumpstarter.common.streams import connect_router_stream
from jumpstarter.v1 import jumpstarter_pb2, jumpstarter_pb2_grpc, kubernetes_pb2

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class Lease(AbstractContextManager, AbstractAsyncContextManager):
    channel: Channel
    timeout: int = 1800
    metadata_filter: MetadataFilter
    portal: BlockingPortal
    controller: jumpstarter_pb2_grpc.ControllerServiceStub = field(init=False)

    def __post_init__(self):
        self.controller = jumpstarter_pb2_grpc.ControllerServiceStub(self.channel)
        self.manager = self.portal.wrap_async_context_manager(self)

    async def __aenter__(self):
        duration = duration_pb2.Duration()
        duration.FromSeconds(self.timeout)

        logger.info("Leasing Exporter matching labels %s for %s", self.metadata_filter.labels, duration)
        self.lease = await self.controller.RequestLease(
            jumpstarter_pb2.RequestLeaseRequest(
                duration=duration,
                selector=kubernetes_pb2.LabelSelector(match_labels=self.metadata_filter.labels),
            )
        )
        logger.info("Lease %s created", self.lease.name)

        with fail_after(300):  # TODO: configurable timeout
            while True:
                logger.info("Polling Lease %s", self.lease.name)
                result = await self.controller.GetLease(jumpstarter_pb2.GetLeaseRequest(name=self.lease.name))

                # lease ready
                if condition_true(result.conditions, "Ready"):
                    logger.info("Lease %s acquired", self.lease.name)
                    return self
                # lease unsatisfiable
                if condition_true(result.conditions, "Unsatisfiable"):
                    raise ValueError("lease unsatisfiable")
                # lease not pending
                if condition_false(result.conditions, "Pending"):
                    raise ValueError("lease not pending")

                await sleep(1)

    async def __aexit__(self, exc_type, exc_value, traceback):
        logger.info("Releasing Lease %s", self.lease.name)
        await self.controller.ReleaseLease(jumpstarter_pb2.ReleaseLeaseRequest(name=self.lease.name))

    def __enter__(self):
        return self.manager.__enter__()

    def __exit__(self, exc_type, exc_value, traceback):
        return self.manager.__exit__(exc_type, exc_value, traceback)

    async def handle_async(self, stream):
        logger.info("Connecting to Lease with name %s", self.lease.name)
        response = await self.controller.Dial(jumpstarter_pb2.DialRequest(lease_name=self.lease.name))
        async with connect_router_stream(response.router_endpoint, response.router_token, stream):
            pass

    @asynccontextmanager
    async def connect_async(self):
        with TemporarySocket() as path:
            async with await create_unix_listener(path) as listener:
                async with create_task_group() as tg:
                    tg.start_soon(listener.serve, self.handle_async, tg)
                    async with grpc.aio.secure_channel(
                        f"unix://{path}", grpc.local_channel_credentials(grpc.LocalConnectionType.UDS)
                    ) as channel:
                        yield await client_from_channel(channel, self.portal)
                    tg.cancel_scope.cancel()

    @contextmanager
    def connect(self):
        with self.portal.wrap_async_context_manager(self.connect_async()) as client:
            yield client
