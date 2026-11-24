"""A returning user's device becomes familiar.

Each login runs the real decision, then is completed as the login webhook
completes it, so the next decision reads it as history. Run against the database,
because the defect lived in which device hash a login stored and which one the
next login looked up: on a screen size that is not exactly a common one, the
first logins stored the hash of the raw size and later logins looked up the hash
of the rounded size, so device familiarity never left its prior.
"""

import uuid

import pytest
from sqlalchemy import select, update

from src.core.config.environment import MIN_AUTH_EVENTS
from src.core.database import DB
from src.data.factory.decision_params import DecisionParamsFactory
from src.data.model import AuthProcess
from src.data.schema import DecisionRequest
from src.service.decision import DecisionService

pytestmark = pytest.mark.asyncio(loop_scope="session")

# A laptop's screen, not in the common list, so it is rounded for the device
# fingerprint. 1920x1080 is in the list and rounds to itself.
LAPTOP_SCREEN = "1728x1117"
COMMON_SCREEN = "1920x1080"
REALM = "prod"


async def _login(user_id: str, screen: str) -> uuid.UUID:
    """One login: the decision, then the completion the webhook would record."""
    event_id = uuid.uuid4()
    await DecisionService(
        DecisionRequest(
            event_id=str(event_id),
            group_id="default",
            realm_id=REALM,
            user_id=user_id,
            client="account-console",
            ip_address="192.0.2.1",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
            ),
            system_language="en-US",
            screen_resolution=screen,
        )
    )()
    async with DB.get_session()() as session:
        await session.execute(
            update(AuthProcess).where(AuthProcess.id == event_id).values(final_status="LOGIN")
        )
        await session.commit()
    return event_id


async def _processes(user_id: str) -> list[AuthProcess]:
    async with DB.get_session()() as session:
        result = await session.execute(select(AuthProcess).where(AuthProcess.user_id == user_id))
        return list(result.scalars().all())


@pytest.mark.parametrize("screen", [LAPTOP_SCREEN, COMMON_SCREEN])
async def test_a_returning_users_device_becomes_familiar(screen):
    await DecisionParamsFactory.ensure_default_params_exist()
    user_id = str(uuid.uuid4())

    # Through the history gate, then two more logins scored on that history.
    last = None
    for _ in range(MIN_AUTH_EVENTS + 2):
        last = await _login(user_id, screen)

    processes = await _processes(user_id)
    hashes = {p.device_info_hash for p in processes}
    assert len(hashes) == 1, (
        f"{len(processes)} logins from one device stored {len(hashes)} device hashes; "
        "a login must store the hash the next one looks up"
    )
    newest = next(p for p in processes if p.id == last)
    assert newest.device_credibility is not None and newest.device_credibility > 0.2, (
        f"device credibility {newest.device_credibility} after {len(processes) - 1} "
        "logins from the same device; it stayed at its 0.2 prior"
    )
