"""The decision's allow and deny lists for the operating system.

The list holds what an admin typed; the login carries the user-agent parser's OS
family. A deny-list entry that silently never matches leaves the admin believing a
control is active when it is not, so the OS lists match the way the admin meant.
The IP and country lists are unchanged: they compare exactly.
"""

from src.service.decision import DecisionService


def service(**lists) -> DecisionService:
    """Only the state the list checks read; see test_familiarity_rule.py."""
    svc = DecisionService.__new__(DecisionService)
    svc.decision_params = {
        name: {"disabled": False, **entry} for name, entry in lists.items()
    }
    return svc


def denied(svc, event):
    return svc._DecisionService__detect_param_blacklist(event)


def allowed(svc, event):
    return svc._DecisionService__detect_param_whitelist(event)


def test_a_deny_list_entry_written_as_people_name_the_os_matches():
    svc = service(operating_system={"blacklist": ["macOS"]})

    assert denied(svc, {"operating_system": "Mac OS X"}) == [
        {"operating_system": "Mac OS X"}
    ]


def test_a_linux_deny_list_entry_matches_a_distribution():
    svc = service(operating_system={"blacklist": ["linux"]})

    assert denied(svc, {"operating_system": "Ubuntu"}) == [{"operating_system": "Ubuntu"}]


def test_an_allow_list_entry_matches_case_insensitively():
    svc = service(operating_system={"whitelist": ["windows"]})

    assert allowed(svc, {"operating_system": "Windows"}) == [
        {"operating_system": "Windows"}
    ]


def test_an_os_list_does_not_match_another_os():
    svc = service(operating_system={"blacklist": ["Windows"], "whitelist": ["iOS"]})
    event = {"operating_system": "Mac OS X"}

    assert denied(svc, event) == []
    assert allowed(svc, event) == []


def test_ip_and_country_lists_still_compare_exactly():
    svc = service(
        ip_address={"blacklist": ["203.0.113.9"]},
        country_name={"blacklist": ["KR"]},
    )

    assert denied(svc, {"ip_address": "203.0.113.9", "country_name": "kr"}) == [
        {"ip_address": "203.0.113.9"}
    ]
