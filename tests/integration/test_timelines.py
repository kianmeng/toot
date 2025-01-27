import pytest

from uuid import uuid4
from tests.utils import run_with_retries

from toot import api, cli
from toot.entities import from_dict, Status
from tests.integration.conftest import TOOT_TEST_BASE_URL, register_account


# TODO: If fixture is not overriden here, tests fail, not sure why, figure it out
@pytest.fixture(scope="module")
def user(app):
    return register_account(app)


@pytest.fixture(scope="module")
def other_user(app):
    return register_account(app)


@pytest.fixture(scope="module")
def friend_user(app, user):
    friend = register_account(app)
    friend_account = api.find_account(app, user, friend.username)
    api.follow(app, user, friend_account["id"])
    return friend


@pytest.fixture(scope="module")
def friend_list(app, user, friend_user):
    friend_account = api.find_account(app, user, friend_user.username)
    list = api.create_list(app, user, str(uuid4())).json()
    api.add_accounts_to_list(app, user, list["id"], account_ids=[friend_account["id"]])
    return list


def test_timelines(app, user, other_user, friend_user, friend_list, run):
    status1 = _post_status(app, user, "#foo")
    status2 = _post_status(app, other_user, "#bar")
    status3 = _post_status(app, friend_user, "#foo #bar")

    # Home timeline
    def test_home():
        result = run(cli.timelines.timeline)
        assert result.exit_code == 0
        assert status1.id in result.stdout
        assert status2.id not in result.stdout
        assert status3.id in result.stdout
    run_with_retries(test_home)

    # Public timeline
    result = run(cli.timelines.timeline, "--public")
    assert result.exit_code == 0
    assert status1.id in result.stdout
    assert status2.id in result.stdout
    assert status3.id in result.stdout

    # Anon public timeline
    result = run(cli.timelines.timeline, "--instance", TOOT_TEST_BASE_URL, "--public")
    assert result.exit_code == 0
    assert status1.id in result.stdout
    assert status2.id in result.stdout
    assert status3.id in result.stdout

    # Tag timeline
    result = run(cli.timelines.timeline, "--tag", "foo")
    assert result.exit_code == 0
    assert status1.id in result.stdout
    assert status2.id not in result.stdout
    assert status3.id in result.stdout

    result = run(cli.timelines.timeline, "--tag", "bar")
    assert result.exit_code == 0
    assert status1.id not in result.stdout
    assert status2.id in result.stdout
    assert status3.id in result.stdout

    # Anon tag timeline
    result = run(cli.timelines.timeline, "--instance", TOOT_TEST_BASE_URL, "--tag", "foo")
    assert result.exit_code == 0
    assert status1.id in result.stdout
    assert status2.id not in result.stdout
    assert status3.id in result.stdout

    # List timeline (by list name)
    result = run(cli.timelines.timeline, "--list", friend_list["title"])
    assert result.exit_code == 0
    assert status1.id not in result.stdout
    assert status2.id not in result.stdout
    assert status3.id in result.stdout

    # List timeline (by list ID)
    result = run(cli.timelines.timeline, "--list", friend_list["id"])
    assert result.exit_code == 0
    assert status1.id not in result.stdout
    assert status2.id not in result.stdout
    assert status3.id in result.stdout

    # Account timeline
    result = run(cli.timelines.timeline, "--account", friend_user.username)
    assert result.exit_code == 0
    assert status1.id not in result.stdout
    assert status2.id not in result.stdout
    assert status3.id in result.stdout

    result = run(cli.timelines.timeline, "--account", other_user.username)
    assert result.exit_code == 0
    assert status1.id not in result.stdout
    assert status2.id in result.stdout
    assert status3.id not in result.stdout


def test_empty_timeline(app, run_as):
    user = register_account(app)
    result = run_as(user, cli.timelines.timeline)
    assert result.exit_code == 0
    assert result.stdout.strip() == "─" * 80


def test_timeline_cant_combine_timelines(run):
    result = run(cli.timelines.timeline, "--tag", "foo", "--account", "bar")
    assert result.exit_code == 1
    assert result.stderr.strip() == "Error: Only one of --public, --tag, --account, or --list can be used at one time."


def test_timeline_local_needs_public_or_tag(run):
    result = run(cli.timelines.timeline, "--local")
    assert result.exit_code == 1
    assert result.stderr.strip() == "Error: The --local option is only valid alongside --public or --tag."


def test_timeline_instance_needs_public_or_tag(run):
    result = run(cli.timelines.timeline, "--instance", TOOT_TEST_BASE_URL)
    assert result.exit_code == 1
    assert result.stderr.strip() == "Error: The --instance option is only valid alongside --public or --tag."


def test_bookmarks(app, user, run):
    status1 = _post_status(app, user)
    status2 = _post_status(app, user)

    api.bookmark(app, user, status1.id)
    api.bookmark(app, user, status2.id)

    result = run(cli.timelines.bookmarks)
    assert result.exit_code == 0
    assert status1.id in result.stdout
    assert status2.id in result.stdout
    assert result.stdout.find(status1.id) > result.stdout.find(status2.id)


    result = run(cli.timelines.bookmarks, "--reverse")
    assert result.exit_code == 0
    assert status1.id in result.stdout
    assert status2.id in result.stdout
    assert result.stdout.find(status1.id) < result.stdout.find(status2.id)


def test_notifications(app, user, other_user, run):
    result = run(cli.timelines.notifications)
    assert result.exit_code == 0
    assert result.stdout.strip() == "You have no notifications"

    text = f"Paging doctor @{user.username}"
    status = _post_status(app, other_user, text)

    def test_notifications():
        result = run(cli.timelines.notifications)
        assert result.exit_code == 0
        assert f"@{other_user.username} mentioned you" in result.stdout
        assert status.id in result.stdout
        assert text in result.stdout
    run_with_retries(test_notifications)

    result = run(cli.timelines.notifications, "--mentions")
    assert result.exit_code == 0
    assert f"@{other_user.username} mentioned you" in result.stdout
    assert status.id in result.stdout
    assert text in result.stdout


def test_notifications_follow(app, user, friend_user, run_as):
    result = run_as(friend_user, cli.timelines.notifications)
    assert result.exit_code == 0
    assert f"@{user.username} now follows you" in result.stdout

    result = run_as(friend_user, cli.timelines.notifications, "--mentions")
    assert result.exit_code == 0
    assert "now follows you" not in result.stdout


def _post_status(app, user, text=None) -> Status:
    text = text or str(uuid4())
    response = api.post_status(app, user, text)
    return from_dict(Status, response.json())
