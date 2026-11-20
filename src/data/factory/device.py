from src.data.schema import DecisionRequest, AuthContextSchema
from src.utils.data_processing.user_agent import UserAgentInfo
from src.utils.data_processing.hash import hash_str
from src.data.model import Device
from src.data.repository import DeviceRepository
from src.core.config.environment import DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION
import logging


class DeviceFactory:

    @staticmethod
    async def identify_from_auth_request(
        request: DecisionRequest | AuthContextSchema,
    ) -> str:
        agent_info = UserAgentInfo(request.user_agent)
        # A login without a screen resolution is fingerprinted with an empty one,
        # the same value its event webhook carries, so both name one device.
        screen_resolution = request.screen_resolution or ""

        browser_signal = agent_info.get_browser_signal(
            DEVICE_SIGNAL_INCLUDE_BROWSER_VERSION
        )

        attrs = [
            str(request.client),
            str(screen_resolution),
            str(request.system_language),
            str(agent_info.get_device()),
            str(browser_signal),
            str(agent_info.get_os_family_major()),
        ]

        content_str = "|".join(attrs)
        device_hash = hash_str(content_str)

        # The database, not a cache, says whether the device is known: every row
        # stored for this login refers to it.
        created = await DeviceRepository.ensure_device(
            Device(
                hash=device_hash,
                device=str(agent_info.get_device()),
                client=str(request.client),
                system_language=str(request.system_language),
                screen_resolution=str(screen_resolution),
                operating_system=str(agent_info.get_os_family_major()),
                browser=str(browser_signal),
            )
        )
        if created:
            logging.info(f"Created new device object | hash {device_hash}")

        return device_hash
