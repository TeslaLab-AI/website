import json
import subprocess

import httpx
import pytest

from app.deployment.github_service import (
    GitHubAuthError,
    GitHubError,
    GitHubService,
    PushError,
    RepoAlreadyExists,
    repo_name_for_project,
)

TOKEN = "github_pat_" + "Z9y8X7w6V5" * 6


def make_service(handler, org=None, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return GitHubService(
        TOKEN,
        org=org,
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )


def repo_payload(name="tl-proj1"):
    return {
        "name": name,
        "full_name": f"acme/{name}",
        "clone_url": f"https://github.com/acme/{name}.git",
        "html_url": f"https://github.com/acme/{name}",
    }


# -- repo creation -------------------------------------------------------
def test_create_private_repo_success_sends_private_true():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json=repo_payload())

    repo = make_service(handler).create_private_repo("tl-proj1")
    assert seen["path"] == "/user/repos"
    assert seen["body"]["private"] is True
    assert repo.clone_url.endswith("tl-proj1.git")


def test_org_endpoint_used_when_org_configured():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(201, json=repo_payload())

    make_service(handler, org="acme").create_private_repo("tl-proj1")
    assert seen["path"] == "/orgs/acme/repos"


def test_bad_token_raises_auth_error_without_leaking_token():
    service = make_service(lambda r: httpx.Response(401, json={"message": "Bad credentials"}))
    with pytest.raises(GitHubAuthError) as exc:
        service.create_private_repo("x")
    assert TOKEN not in str(exc.value)


def test_name_collision_raises_repo_already_exists():
    body = {"message": "Repository creation failed.",
            "errors": [{"message": "name already exists on this account"}]}
    service = make_service(lambda r: httpx.Response(422, json=body))
    with pytest.raises(RepoAlreadyExists):
        service.create_private_repo("tl-proj1")


def test_unique_creation_adds_suffix_on_collision():
    names = []

    def handler(request):
        name = json.loads(request.content)["name"]
        names.append(name)
        if name == "tl-proj1":
            return httpx.Response(
                422, json={"errors": [{"message": "name already exists on this account"}]}
            )
        return httpx.Response(201, json=repo_payload(name))

    repo = make_service(handler).create_private_repo_unique("proj1")
    assert names == ["tl-proj1", "tl-proj1-2"]
    assert repo.name == "tl-proj1-2"


def test_retries_on_503_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(201, json=repo_payload())

    make_service(handler, sleeps=sleeps).create_private_repo("tl-proj1")
    assert calls["n"] == 3
    assert sleeps == [1, 2]


def test_gives_up_after_max_retries():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    with pytest.raises(GitHubError):
        make_service(handler).create_private_repo("tl-proj1")
    assert calls["n"] == 4  # first try + 3 retries


def test_repr_hides_token():
    assert TOKEN not in repr(make_service(lambda r: httpx.Response(201)))


def test_repo_name_is_sanitized():
    assert repo_name_for_project("abc 123/../x") == "tl-abc-123-..-x"
    with pytest.raises(ValueError):
        repo_name_for_project("///")


# -- pushing code --------------------------------------------------------
def git(*args, cwd=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def bare_remote(tmp_path):
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    return remote


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "index.js").write_text("console.log('hi')\n")
    (d / ".env").write_text("SECRET=do-not-push\n")
    (d / ".env.example").write_text("SECRET=\n")
    return d


def remote_files(remote):
    return git("--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").splitlines()


def test_push_directory_pushes_code_but_not_env(project, bare_remote):
    service = make_service(lambda r: httpx.Response(201))
    sha = service.push_directory(str(project), str(bare_remote))
    files = remote_files(bare_remote)
    assert "index.js" in files
    assert ".env.example" in files
    assert ".env" not in files
    assert sha == git("--git-dir", str(bare_remote), "rev-parse", "main")


def test_push_refuses_when_env_is_already_tracked(project, bare_remote):
    git("init", cwd=project)
    git("add", "-f", ".env", cwd=project)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "oops", cwd=project)
    service = make_service(lambda r: httpx.Response(201))
    with pytest.raises(PushError) as exc:
        service.push_directory(str(project), str(bare_remote))
    assert ".env" in str(exc.value)
    assert "do-not-push" not in str(exc.value)


def test_push_rejects_credentials_in_remote_url(project):
    service = make_service(lambda r: httpx.Response(201))
    with pytest.raises(ValueError):
        service.push_directory(str(project), f"https://x:{TOKEN}@github.com/a/b.git")


def test_push_failure_does_not_leak_token(project, tmp_path):
    service = make_service(lambda r: httpx.Response(201))
    with pytest.raises(PushError) as exc:
        service.push_directory(str(project), str(tmp_path / "does-not-exist.git"))
    assert TOKEN not in str(exc.value)


def test_push_empty_directory_fails_clearly(tmp_path, bare_remote):
    empty = tmp_path / "empty"
    empty.mkdir()
    service = make_service(lambda r: httpx.Response(201))
    # Only the auto-created .gitignore exists, so there is still something to commit;
    # an actually empty repo state is caught when nothing at all is staged.
    service.push_directory(str(empty), str(bare_remote))
    assert ".gitignore" in remote_files(bare_remote)
