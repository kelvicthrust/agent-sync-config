#!/usr/bin/env python3
"""Share local agent configuration without overwriting conflicting content."""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager

sys.dont_write_bytecode = True

VERSION = "0.3.0"
NAME = "agent-sync-config"
SCHEMA = 1
SKILL = Path(__file__).resolve().parents[1]
BEGIN = "<!-- agent-sync-config:start -->"
END = "<!-- agent-sync-config:end -->"
GUIDANCE = f"""{BEGIN}
## Shared agent configuration

This repository uses agent-sync-config to share instructions, skills, curated
context, and MCP configuration across Codex and Claude Code.

Use the agent-sync-config skill after changing shared configuration, when hooks
report drift or conflicts, or when switching clients without an automatic check.
Claude Code: /agent-sync-config. Codex CLI/IDE: $agent-sync-config.
Codex desktop: select agent-sync-config with @.

Project synchronization uses `--scope project`; global configuration changes
require a separate explicit `--scope global` command and do not modify this repo.
For read-only verification, run `agent-sync-config check --scope project`.
Edit shared instructions here, skills in `.agents/skills/`, context in
`.agents/context/`, and MCP definitions in `.agents/mcp.json`.
Project setup packages this skill in `.agents/skills/agent-sync-config/`.
Preserve conflicting content and reconcile it before syncing. References alone
do not install skills; automatic checks require enabled, trusted hooks.
{END}
"""
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
CREDENTIAL = re.compile(r"token|password|secret|api[_-]?key", re.I)
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ConfigError(Exception):
    pass


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def read_json(path: Path, default=None):
    if not exists(path):
        return copy.deepcopy(default)
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Cannot read JSON: {path} ({type(exc).__name__})") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Expected a JSON object: {path}")
    return value


def json_text(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_digest(path: Path) -> str:
    """Used only during explicit adoption/installation, never warm prompt checks."""
    h = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        h.update(str(item.relative_to(path)).encode())
        if item.is_symlink():
            h.update(os.readlink(item).encode())
        elif item.is_file():
            h.update(item.read_bytes())
    return h.hexdigest()


def validate_links(records: dict, personal: bool = False):
    roots = {".claude/skills", ".codex/skills"}
    if personal:
        roots.add(".agents/skills")
    instructions = {".codex/AGENTS.md", ".claude/CLAUDE.md"} if personal else {".claude/context", ".codex/context"}
    for key, value in records.items():
        path = Path(key)
        valid_skill = str(path.parent) in roots and SKILL_NAME.fullmatch(path.name)
        if not isinstance(value, str) or not (valid_skill or key in instructions):
            raise ConfigError("Invalid managed link path; preserve the manifest and reconcile it")


def portable_skill(source: Path):
    if not SKILL_NAME.fullmatch(source.name) or not (source / "SKILL.md").is_file():
        raise ConfigError("Skill directory needs a lowercase hyphenated name and SKILL.md")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ConfigError("Skill contains dependency symlinks; make it self-contained before adoption")
        if path.is_file() and path.suffix != ".pyc":
            data = path.read_bytes()
            if re.search(rb"\$\{?(?:CLAUDE_)?PLUGIN_(?:ROOT|DATA)", data):
                raise ConfigError("Skill depends on plugin runtime paths; adapt dependencies before adoption")


def toml_module():
    vendor = str(Path(__file__).resolve().parent / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import tomlkit
    return tomlkit


def read_toml(path: Path):
    tk = toml_module()
    try:
        return tk.parse(path.read_text()) if exists(path) else tk.document()
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Cannot read TOML: {path} ({type(exc).__name__})") from exc


def plain(value):
    return value.unwrap() if hasattr(value, "unwrap") else value


def update_toml_table(table, desired):
    """Change owned keys in place so tomlkit retains surrounding comments."""
    for key in list(table):
        if key not in desired:
            del table[key]
    for key, value in desired.items():
        if isinstance(value, dict) and key in table and isinstance(plain(table[key]), dict):
            update_toml_table(table[key], value)
        else:
            table[key] = value


def root_for(path: Path) -> Path:
    """Walk to the worktree root without spawning git on every prompt."""
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(f"Project directory does not exist: {path}")
    for candidate in (path, *path.parents):
        if exists(candidate / ".git"):
            return candidate
    for candidate in (path, *path.parents):
        if (candidate / ".agents/agent-sync.json").is_file():
            return candidate
    return path


def project_hook_command(provider: str) -> str:
    # The native hook supplies cwd on stdin. Locate the vendored runtime before
    # loading it, even when invoked from a nested directory or a moved checkout.
    bootstrap = '''import io,json,os,runpy,sys
from pathlib import Path
raw=sys.stdin.read()
event="UserPromptSubmit"
try:
    payload=json.loads(raw)
    event=payload.get("hook_event_name",event)
    cwd=Path(payload.get("cwd",os.getcwd())).resolve()
    candidates=(cwd,*cwd.parents)
    root=next((p for p in candidates if (p/".git").exists()),None)
    if root is None:
        root=next((p for p in candidates if (p/".agents/agent-sync.json").is_file()),cwd)
    script=root/".agents/skills/agent-sync-config/scripts/agent_sync_config.py"
    if not script.is_file():
        raise OSError("Missing project runtime")
except (OSError,ValueError,TypeError,AttributeError):
    print(json.dumps({"hookSpecificOutput":{"hookEventName":event,"additionalContext":"agent-sync-config: project hook cannot locate its runtime. Run agent-sync-config --scope project."}}))
    sys.exit(0)
sys.stdin=io.StringIO(raw)
sys.argv=[str(script),"hook","--scope","project","--provider",sys.argv[1]]
runpy.run_path(str(script),run_name="__main__")
'''
    return shlex.join(["python3", "-c", bootstrap, provider])


def project_config_exists(root: Path) -> bool:
    return any(exists(root / name) for name in (".agents", ".claude", ".codex",
               "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", ".mcp.json"))


def strip_guidance(text: str) -> str:
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ConfigError("Malformed agent-sync-config instruction markers")
    if BEGIN in text:
        start, finish = text.index(BEGIN), text.index(END) + len(END)
        if finish < start:
            raise ConfigError("Reversed agent-sync-config instruction markers")
        return (text[:start] + text[finish:]).strip()
    return text.strip()


def add_guidance(text: str) -> str:
    strip_guidance(text)  # validate markers before editing
    if BEGIN in text:
        start, finish = text.index(BEGIN), text.index(END) + len(END)
        return text[:start] + GUIDANCE.rstrip() + text[finish:]
    return text.rstrip() + "\n\n" + GUIDANCE


def validate_server(server: dict) -> dict:
    allowed = {"transport", "command", "args", "cwd", "env", "env_vars", "url",
               "headers", "env_headers", "bearer_token_env_var"}
    if not isinstance(server, dict) or set(server) - allowed:
        raise ConfigError("Unsupported shared MCP fields; preserve provider-specific options separately")
    result = copy.deepcopy(server)
    transport = result.get("transport")
    if transport not in ("stdio", "http"):
        raise ConfigError("MCP transport must be stdio or http")
    required = "command" if transport == "stdio" else "url"
    if not isinstance(result.get(required), str) or not result[required]:
        raise ConfigError(f"MCP {required} must be a nonempty string")
    if transport == "stdio" and set(result) & {"url", "headers", "env_headers", "bearer_token_env_var"}:
        raise ConfigError("HTTP-only fields on a stdio MCP server")
    if transport == "http" and set(result) & {"command", "args", "cwd", "env", "env_vars"}:
        raise ConfigError("Stdio-only fields on an HTTP MCP server")
    for key in ("cwd", "bearer_token_env_var"):
        if key in result and not isinstance(result[key], str):
            raise ConfigError(f"MCP {key} must be a string")
    for key in ("args", "env_vars"):
        if key in result and (not isinstance(result[key], list) or
                              not all(isinstance(x, str) for x in result[key])):
            raise ConfigError(f"MCP {key} must be a list of strings")
    for key in ("env", "headers", "env_headers"):
        if key in result and (not isinstance(result[key], dict) or
                              not all(isinstance(v, str) for v in result[key].values())):
            raise ConfigError(f"MCP {key} must map names to strings")
    for value in [result.get("command", ""), result.get("url", ""), result.get("cwd", ""), *result.get("args", [])]:
        if "${" in value:
            raise ConfigError("Provider-specific interpolation in MCP paths/URLs is not portable; use literal paths/URLs")
    names = result.get("env_vars", []) + list(result.get("env_headers", {}).values())
    if "bearer_token_env_var" in result:
        names.append(result["bearer_token_env_var"])
    if any(not ENV_NAME.fullmatch(name) for name in names):
        raise ConfigError("Invalid MCP environment variable name")
    if set(result.get("env", {})) & set(result.get("env_vars", [])):
        raise ConfigError("MCP env and env_vars overlap")
    if set(result.get("headers", {})) & set(result.get("env_headers", {})):
        raise ConfigError("MCP headers and env_headers overlap")
    if "bearer_token_env_var" in result and "authorization" in {
            key.lower() for key in list(result.get("headers", {})) + list(result.get("env_headers", {}))}:
        raise ConfigError("MCP Authorization header and bearer token overlap")
    for key, value in result.get("env", {}).items():
        if CREDENTIAL.search(key) or "${" in value:
            raise ConfigError("Use env_vars for credentials/interpolation; env is for literal nonsecret values")
    for key, value in result.get("headers", {}).items():
        if key.lower() == "authorization" or CREDENTIAL.search(key) or "${" in value:
            raise ConfigError("Use env_headers or bearer_token_env_var for credential headers")
    return {k: v for k, v in result.items() if v not in ({}, [])}


def render_server(server: dict, provider: str) -> dict:
    server = validate_server(server)
    out = {k: copy.deepcopy(v) for k, v in server.items()
           if k not in {"transport", "env_vars", "headers", "env_headers", "bearer_token_env_var"}}
    if provider == "codex":
        for key in ("env_vars", "bearer_token_env_var"):
            if key in server:
                out[key] = server[key]
        if server.get("headers"):
            out["http_headers"] = server["headers"]
        if server.get("env_headers"):
            out["env_http_headers"] = server["env_headers"]
    else:
        out["type"] = server["transport"]
        if "cwd" in out:
            raise ConfigError("Claude project MCP has no portable cwd field; use absolute command/argument paths")
        env = out.setdefault("env", {})
        env.update({name: "${" + name + "}" for name in server.get("env_vars", [])})
        headers = copy.deepcopy(server.get("headers", {}))
        headers.update({key: "${" + name + "}" for key, name in server.get("env_headers", {}).items()})
        if "bearer_token_env_var" in server:
            headers["Authorization"] = "Bearer ${" + server["bearer_token_env_var"] + "}"
        if headers:
            out["headers"] = headers
        if not env:
            del out["env"]
    return out


def import_server(native: dict, provider: str) -> dict:
    native = plain(native)
    if not isinstance(native, dict):
        raise ConfigError("MCP definition must be an object")
    if provider == "codex":
        out = copy.deepcopy(native)
        out["transport"] = "http" if "url" in out else "stdio"
        if "http_headers" in out:
            out["headers"] = out.pop("http_headers")
        if "env_http_headers" in out:
            out["env_headers"] = out.pop("env_http_headers")
    else:
        out = copy.deepcopy(native)
        out["transport"] = out.pop("type", "http" if "url" in out else "stdio")
        inherited = []
        for key, value in list(out.get("env", {}).items()):
            match = ENV_REF.fullmatch(value) if isinstance(value, str) else None
            if match:
                if key != match[1]:
                    raise ConfigError("Aliased MCP environment variables are not portable to Codex")
                inherited.append(key)
                del out["env"][key]
        if inherited:
            out["env_vars"] = inherited
        for key, value in list(out.get("headers", {}).items()):
            bearer = re.fullmatch(r"Bearer \$\{([A-Za-z_][A-Za-z0-9_]*)\}", value) if isinstance(value, str) else None
            match = ENV_REF.fullmatch(value) if isinstance(value, str) else None
            if key.lower() == "authorization" and bearer:
                out["bearer_token_env_var"] = bearer[1]
                del out["headers"][key]
            elif match:
                out.setdefault("env_headers", {})[key] = match[1]
                del out["headers"][key]
    return validate_server(out)


class Sync:
    def __init__(self, home: Path, root: Path | None, apply: bool, personal: Path | None = None,
                 scope: str = "project", hook: bool = False):
        self.home, self.root, self.apply = home, root, apply
        self.scope, self.hook = scope, hook
        self.state_dir = home / ".local/state/agent-sync-config"
        self.registry_path = self.state_dir / "registry.json"
        self.registry = read_json(self.registry_path, {"schema": SCHEMA, "projects": {}})
        if self.registry.get("schema") != SCHEMA or not isinstance(self.registry.get("projects"), dict):
            raise ConfigError("Unsupported machine registry")
        recovery = self.registry.get("global_uninstall", {})
        if not isinstance(recovery, dict):
            raise ConfigError("Invalid global uninstall recovery state")
        registered = self.registry.get("personal_root") or recovery.get("personal_root")
        if personal and registered and personal.resolve() != Path(registered).resolve():
            raise ConfigError("Personal root already registered; migrate it explicitly rather than creating a second source")
        self.personal = personal or (Path(registered) if registered else home / "agent-config")
        self.personal = self.personal.expanduser().resolve()
        self.restoring: set[str] = set()
        self.pending_removals: dict = {}
        self.issues: list[str] = []
        self.changes: list[str] = []
        self.notes: list[str] = []
        if scope == "project":
            if root == home or root.is_relative_to(self.personal) or any(
                    root.is_relative_to(home / name) for name in (".agents", ".claude", ".codex")):
                raise ConfigError("Choose a project directory outside personal/global configuration, or use --scope global")
        self.old = read_json(root / ".agents/agent-sync.json", None) if scope == "project" else None
        if self.old is not None and (self.old.get("schema") != SCHEMA or
                                     not isinstance(self.old.get("links"), dict) or
                                     not isinstance(self.old.get("mcp"), dict)):
            raise ConfigError("Unsupported project manifest; do not overwrite it")
        self.manifest = copy.deepcopy(self.old) if self.old is not None else {
            "schema": SCHEMA, "links": {}, "mcp": {}, "instructions": {}}
        validate_links(self.manifest["links"])

    def safe_parent(self, path: Path):
        allowed = (self.root, self.state_dir) if self.scope == "project" else (self.personal, self.home)
        xdg = os.environ.get("XDG_STATE_HOME")
        if self.scope == "global" and xdg and self.home == Path.home().resolve() and Path(xdg).is_absolute():
            allowed += (Path(xdg).expanduser() / "skills",)
        bases = sorted(allowed, key=lambda item: len(item.parts), reverse=True)
        for base in bases:
            if path.is_relative_to(base):
                for parent in path.parents:
                    if parent == base:
                        break
                    if parent.is_symlink():
                        raise ConfigError(f"Refusing to write through a linked configuration directory: {parent}")
                return
        raise ConfigError(f"Refusing to write outside {self.scope} scope: {path}")

    def issue(self, message: str):
        if message not in self.issues:
            self.issues.append(message)

    def changed(self, message: str):
        if message not in self.changes:
            self.changes.append(message)

    def backup(self, path: Path):
        if not exists(path):
            return
        identifier = digest(str(path).encode())[:16]
        fingerprint = (digest(os.readlink(path).encode()) if path.is_symlink() else
                       tree_digest(path) if path.is_dir() else digest(path.read_bytes()))
        dest = self.state_dir / "backups" / identifier / fingerprint
        if exists(dest):
            return
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            dest.symlink_to(os.readlink(path))
        elif path.is_dir():
            shutil.copytree(path, dest, symlinks=True)
        else:
            shutil.copy2(path, dest)
            dest.chmod(0o600)

    def write(self, path: Path, text: str, mode: int | None = None):
        self.safe_parent(path)
        if path.is_symlink():
            raise ConfigError(f"Refusing to replace a configuration symlink: {path}")
        if exists(path) and path.is_file() and path.read_text() == text:
            if mode is not None and path.stat().st_mode & 0o777 != mode:
                self.changed(f"Set permissions: {path}")
                if self.apply:
                    path.chmod(mode)
            return
        self.changed(f"Update: {path}")
        if not self.apply:
            return
        self.backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(text.encode())
        try:
            temp.chmod(mode if mode is not None else path.stat().st_mode & 0o777 if path.exists() else 0o644)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def mkdir(self, path: Path):
        self.safe_parent(path)
        if path.is_dir() and not path.is_symlink():
            return
        if exists(path):
            raise ConfigError(f"Expected an ordinary directory: {path}")
        self.changed(f"Create directory: {path}")
        if self.apply:
            path.mkdir(parents=True, exist_ok=True)

    def link(self, target: Path, source: Path, records: dict, key: str, adopted: bool = False):
        self.safe_parent(target)
        desired = os.path.relpath(source, target.parent)
        if target.is_symlink():
            if target.resolve() == source.resolve():
                # Keep the actual spelling for ownership: Skills CLI often
                # routes Claude through .agents rather than directly to source.
                records[key] = os.readlink(target)
                return
            self.issue(f"Conflicting symlink (preserved): {target}")
            return
        if exists(target):
            if source.resolve() == target.resolve():
                self.issue(f"Canonical resource points back to this provider location; reconcile before linking: {target}")
                return
            same = (target.is_file() and source.is_file() and target.read_bytes() == source.read_bytes()) or (
                target.is_dir() and source.is_dir() and tree_digest(target) == tree_digest(source))
            if not same and not adopted:
                self.issue(f"Conflicting content (preserved): {target}")
                return
        records[key] = desired
        self.changed(f"Link: {target} -> {desired}")
        if self.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.backup(target)
            if target.is_dir():
                shutil.rmtree(target)
            elif exists(target):
                target.unlink()
            target.symlink_to(desired)

    def instructions(self):
        agents = self.root / "AGENTS.md"
        claude = self.root / "CLAUDE.md"
        local_claude = self.root / ".claude/CLAUDE.md"
        if self.hook and not agents.exists():
            self.issue("Shared AGENTS.md is missing; reconcile it explicitly rather than recreating instructions in a hook")
            return
        if agents.is_symlink():
            self.issue(f"Project AGENTS.md is externally linked; reconcile before adoption: {agents}")
            return
        source_text = agents.read_text() if agents.exists() else None
        candidates = []
        for path, wrapper in ((claude, "@AGENTS.md"), (local_claude, "@../AGENTS.md")):
            if exists(path):
                if not path.is_file():
                    self.issue(f"Instruction file is unreadable: {path}")
                    continue
                text = path.read_text()
                if text.strip() == wrapper or (path.is_symlink() and path.resolve() == agents.resolve()):
                    continue
                candidates.append((path, text, wrapper))
        if source_text is None and candidates:
            source_text = candidates[0][1]
        if source_text is None:
            source_text = "# Project instructions\n\nAdd project conventions and build/test commands here.\n"
        compatible = []
        for path, text, wrapper in candidates:
            if strip_guidance(text) != strip_guidance(source_text):
                self.issue(f"Instructions differ from AGENTS.md (preserved): {path}")
            else:
                compatible.append((path, wrapper))
        self.write(agents, add_guidance(source_text))
        if not exists(claude) or claude.read_text().strip() == "@AGENTS.md":
            self.write(claude, "@AGENTS.md\n")
        for path, wrapper in compatible:
            self.write(path, wrapper + "\n")
        self.manifest["instructions"] = {"agents": "AGENTS.md", "claude": "CLAUDE.md"}
        if exists(self.root / "AGENTS.override.md"):
            self.issue("AGENTS.override.md masks shared root instructions in Codex; reconcile it explicitly")

    def skills(self, canonical: Path, targets: list[Path], records: dict, base: Path, blocked=None):
        blocked = blocked or set()
        self.mkdir(canonical)
        for target_dir in targets:
            self.mkdir(target_dir)
            if not target_dir.is_dir() or target_dir.is_symlink():
                continue
            for item in sorted(target_dir.iterdir()):
                if item.name in blocked or item.name.startswith(".") or not (item / "SKILL.md").is_file():
                    continue
                source = canonical / item.name
                if not exists(source):
                    if item.is_symlink():
                        self.issue(f"External skill link needs explicit --import-skill adoption: {item}")
                        continue
                    try:
                        portable_skill(item)
                    except ConfigError as exc:
                        self.issue(f"Cannot adopt skill {item}: {exc}")
                        continue
                    self.changed(f"Adopt skill: {item} -> {source}")
                    if self.apply:
                        shutil.copytree(item, source, symlinks=True)
        if not canonical.is_dir() or canonical.is_symlink():
            return
        wanted = {}
        for source in sorted(canonical.iterdir()):
            if source.name in blocked or source.name.startswith("."):
                continue
            if not SKILL_NAME.fullmatch(source.name):
                self.issue(f"Invalid shared skill directory name: {source}")
                continue
            if not (source / "SKILL.md").is_file():
                self.issue(f"Skill folder lacks SKILL.md: {source}")
                continue
            for target_dir in targets:
                if target_dir.is_symlink():
                    continue
                target = target_dir / source.name
                key = str(target.relative_to(base))
                self.link(target, source, records, key)
                wanted[key] = records.get(key)
        # Remove only links that we owned and that still point to the recorded source.
        prefixes = [str(target.relative_to(base)) + "/" for target in targets]
        for key, previous in list(records.items()):
            if Path(key).name in blocked or key in wanted or not any(key.startswith(prefix) for prefix in prefixes):
                continue
            target = base / key
            if target.is_symlink() and os.readlink(target) == previous:
                self.changed(f"Remove obsolete skill link: {target}")
                if self.apply:
                    target.unlink()
                    del records[key]
            elif exists(target):
                self.issue(f"Modified obsolete skill link (preserved): {target}")
            elif self.apply:
                del records[key]

    def context(self):
        canonical = self.root / ".agents/context"
        self.mkdir(canonical)
        for relative in (".claude/context", ".codex/context"):
            source = self.root / relative
            if not exists(source):
                if relative in self.manifest["links"]:
                    self.link(source, canonical, self.manifest["links"], relative)
                continue
            if source.is_symlink():
                if source.resolve() == canonical.resolve():
                    self.manifest["links"][relative] = os.path.relpath(canonical, source.parent)
                else:
                    self.issue(f"External context link needs explicit reconciliation: {source}")
                continue
            if not source.is_dir():
                self.issue(f"Context location is not a directory: {source}")
                continue
            conflict = False
            for item in sorted(source.rglob("*")):
                target = canonical / item.relative_to(source)
                if item.is_symlink():
                    self.issue(f"Context dependency link needs reconciliation: {item}")
                    conflict = True
                elif item.is_dir():
                    self.mkdir(target)
                elif target.exists() and (not target.is_file() or target.read_bytes() != item.read_bytes()):
                    self.issue(f"Context content differs (preserved): {item}")
                    conflict = True
                elif not target.exists():
                    self.changed(f"Adopt context: {item} -> {target}")
                    if self.apply:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, target)
            if not conflict:
                self.link(source, canonical, self.manifest["links"], relative, adopted=True)

    def mcp_documents(self, personal: bool):
        codex = (self.home if personal else self.root) / ".codex/config.toml"
        claude = self.home / ".claude.json" if personal else self.root / ".mcp.json"
        codex_doc = read_toml(codex)
        features = plain(codex_doc.get("features", {}))
        if isinstance(features, dict) and features.get("hooks", features.get("codex_hooks")) is False:
            self.issue(f"Codex hooks are disabled by configuration (preserved): {codex}")
        return {"codex": (codex, codex_doc, "mcp_servers"),
                "claude": (claude, read_json(claude, {}), "mcpServers")}

    def mcp(self, canonical: Path, records: dict, personal: bool = False, imported: Path | None = None):
        docs = self.mcp_documents(personal)
        neutral = read_json(canonical, None)
        if neutral is None:
            servers = {}
            for provider, (path, doc, key) in docs.items():
                native_servers = doc.get(key, {})
                if not isinstance(plain(native_servers), dict):
                    raise ConfigError(f"Expected MCP server map: {path}")
                for name, native in native_servers.items():
                    try:
                        candidate = import_server(native, provider)
                    except ConfigError as exc:
                        self.issue(f"Cannot adopt MCP {name} from {path}: {exc}")
                        continue
                    if name in servers and servers[name] != candidate:
                        self.issue(f"Provider MCP definitions differ (preserved): {name}")
                        continue
                    servers[name] = candidate
            neutral = {"schema": SCHEMA, "servers": servers}
            if servers:
                self.write(canonical, json_text(neutral))
        if set(neutral) != {"schema", "servers"} or neutral["schema"] != SCHEMA or not isinstance(neutral["servers"], dict):
            raise ConfigError("Shared MCP manifest requires schema: 1 and a servers object")
        if imported:
            imported_doc = read_json(imported, None)
            imported_servers = imported_doc.get("mcpServers") if imported_doc is not None else None
            if not isinstance(imported_servers, dict):
                raise ConfigError("Imported MCP file must contain mcpServers")
            for name, native in imported_servers.items():
                candidate = import_server(native, "claude")
                if name in neutral["servers"] and neutral["servers"][name] != candidate:
                    self.issue(f"Imported MCP conflicts with canonical definition: {name}")
                else:
                    neutral["servers"][name] = candidate
            self.write(canonical, json_text(neutral))
        for provider, (path, doc, key) in docs.items():
            current = doc.get(key, {})
            if not isinstance(plain(current), dict):
                raise ConfigError(f"Expected MCP server map: {path}")
            previous = records.setdefault(provider, {})
            if not isinstance(previous, dict):
                raise ConfigError("Invalid managed MCP state")
            wanted = {}
            for name, server in neutral["servers"].items():
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                    raise ConfigError("Shared MCP names must use letters, digits, underscores, or hyphens")
                try:
                    wanted[name] = render_server(server, provider)
                except ConfigError as exc:
                    self.issue(f"Cannot render MCP {name} for {provider}: {exc}")
            changed = False
            for name, desired in wanted.items():
                actual = plain(current.get(name))
                # Claude's omitted stdio type is semantically equivalent.
                normalized = copy.deepcopy(actual)
                if provider == "claude" and isinstance(normalized, dict) and "command" in normalized:
                    normalized.setdefault("type", "stdio")
                if normalized == desired:
                    previous[name] = actual
                    continue
                if actual is not None and actual != previous.get(name):
                    self.issue(f"Manual MCP edit/conflict (preserved): {path} [{name}]")
                    continue
                self.changed(f"Render MCP: {path} [{name}]")
                changed = True
                if self.apply:
                    if key not in doc:
                        doc[key] = toml_module().table() if provider == "codex" else {}
                    if provider == "codex" and name in doc[key]:
                        update_toml_table(doc[key][name], desired)
                    else:
                        doc[key][name] = desired
                    current = doc[key]
                    previous[name] = desired
            for name, last in list(previous.items()):
                if name in neutral["servers"]:
                    continue
                actual = plain(current.get(name))
                if actual is None:
                    if self.apply:
                        del previous[name]
                elif actual == last:
                    self.changed(f"Remove obsolete MCP: {path} [{name}]")
                    changed = True
                    if self.apply:
                        del doc[key][name]
                        del previous[name]
                else:
                    self.issue(f"Modified obsolete MCP (preserved): {path} [{name}]")
            if changed and self.apply:
                self.write(path, toml_module().dumps(doc) if provider == "codex" else json_text(doc))
                self.notes.append(f"MCP changed for {provider}; reconnect servers or restart that client if necessary.")

    def import_skill(self, source: Path):
        source = source.expanduser().resolve()
        portable_skill(source)
        canonical = self.root / ".agents/skills" if self.scope == "project" else self.personal / "skills"
        target = canonical / source.name
        if exists(target):
            if tree_digest(target) != tree_digest(source):
                self.issue(f"Imported skill conflicts (preserved): {target}")
            return
        self.changed(f"Import skill: {source} -> {target}")
        if self.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)

    def install_hooks(self):
        global_scope = self.scope == "global"
        base = self.home if global_scope else self.root
        records = self.registry if global_scope else self.manifest
        script = self.personal / "skills/agent-sync-config/scripts/agent_sync_config.py"
        for provider, path in (("codex", base / ".codex/hooks.json"),
                               ("claude", base / ".claude/settings.json")):
            doc = read_json(path, {})
            if doc.get("disableAllHooks"):
                self.issue(f"Hooks disabled by existing settings (preserved): {path}")
            hooks = doc.setdefault("hooks", {})
            if not isinstance(hooks, dict):
                raise ConfigError(f"Expected hooks object: {path}")
            command = (shlex.join([sys.executable, str(script), "hook", "--scope", "global",
                                  "--provider", provider, "--home", str(self.home)])
                       if global_scope else project_hook_command(provider))
            old_commands = records.setdefault("hook_commands", {}).get(provider, [])
            for event in ("SessionStart", "UserPromptSubmit"):
                entries = hooks.setdefault(event, [])
                if not isinstance(entries, list):
                    raise ConfigError(f"Expected hook list: {path} [{event}]")
                found = False
                updated = []
                for entry in entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                        raise ConfigError(f"Invalid hook group: {path} [{event}]")
                    remaining = []
                    for handler in entry["hooks"]:
                        if not isinstance(handler, dict):
                            raise ConfigError(f"Invalid hook handler: {path}")
                        if handler.get("command") in old_commands or handler.get("command") == command:
                            if handler.get("command") == command and not found and handler.get("type") == "command" and not handler.get("async"):
                                remaining.append(handler)
                                found = True
                        else:
                            remaining.append(handler)
                    if remaining:
                        updated.append({**entry, "hooks": remaining})
                if not found:
                    updated.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})
                hooks[event] = updated
            self.write(path, json_text(doc), 0o600)
            records["hook_commands"][provider] = [command]
        if global_scope:
            self.registry["global_hooks_audit_only"] = True
        self.notes.append("Review/trust Codex hook definitions in /hooks. Restart Claude Code after initial hook installation. External policy can disable hooks; file presence does not prove execution.")

    def install_runtime(self, canonical: Path, state: dict):
        target = canonical / NAME
        source_hash = tree_digest(SKILL)
        if not exists(target):
            self.changed(f"Install setup skill: {target}")
            if self.apply:
                shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                state["tool_digest"] = source_hash
        elif target.resolve() != SKILL.resolve():
            if target.is_symlink():
                self.issue(f"Setup skill is linked elsewhere; preserve it and install from that source: {target}")
            else:
                installed_hash = tree_digest(target)
                if installed_hash != source_hash:
                    if installed_hash != state.get("tool_digest"):
                        self.issue(f"Setup skill has local edits (preserved): {target}")
                    else:
                        self.changed(f"Upgrade setup skill: {target}")
                        if self.apply:
                            self.backup(target)
                            shutil.rmtree(target)
                            shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                            state["tool_digest"] = source_hash
                else:
                    state["tool_digest"] = source_hash
        else:
            state.setdefault("tool_digest", source_hash)
        return target

    def skill_link_values(self, name, target):
        source = self.personal / "skills" / name
        values = {str(source), os.path.relpath(source, target.parent)}
        native = self.home / ".agents/skills" / name
        if target != native:
            values |= {str(native), os.path.relpath(native, target.parent)}
        return values

    def personal_state(self):
        recovery = self.registry.get("global_uninstall", {})
        default = recovery.get("state", {"schema": SCHEMA, "links": {}, "mcp": {}})
        state = read_json(self.personal / ".agent-sync.json", default)
        if state.get("schema") != SCHEMA or not isinstance(state.get("links"), dict) or not isinstance(state.get("mcp"), dict):
            raise ConfigError("Unsupported personal manifest")
        validate_links(state["links"], personal=True)
        if state.get("lifecycle_version", 1) != 1:
            raise ConfigError("Unsupported global lifecycle manifest")
        if "detached" in state and not isinstance(state["detached"], bool):
            raise ConfigError("Invalid detached global state")
        for field in ("skills", "removed_skills", "shared_files"):
            if not isinstance(state.get(field, {}), dict):
                raise ConfigError(f"Invalid personal {field} state")
        for name, record in state.get("skills", {}).items():
            if not SKILL_NAME.fullmatch(name) or not isinstance(record, dict):
                raise ConfigError("Invalid owned skill record")
            if not re.fullmatch(r"[0-9a-f]{64}", record.get("digest", "")):
                raise ConfigError("Invalid owned skill digest")
            entries = record.get("entrypoints", {})
            if not isinstance(entries, dict):
                raise ConfigError("Invalid owned skill entrypoints")
            validate_links(entries, personal=True)
            if any(Path(key).name != name or str(Path(key).parent) not in {".agents/skills", ".claude/skills", ".codex/skills"}
                   or value not in self.skill_link_values(name, self.home / key)
                   for key, value in entries.items()):
                raise ConfigError("Owned skill entrypoint does not point to its shared source")
            cli = record.get("cli")
            if cli is not None and (not isinstance(cli, dict) or not isinstance(cli.get("path"), str)
                                    or not isinstance(cli.get("entry"), dict) or not isinstance(cli.get("key", name), str)):
                raise ConfigError("Invalid observed Skills CLI metadata")
            if cli is not None:
                normalized = re.sub(r"[^a-z0-9._]+", "-", cli.get("key", name).lower()).strip(".-")[:255] or "unnamed-skill"
                if normalized != name:
                    raise ConfigError("Observed Skills CLI key does not match its owned skill")
        if any(not SKILL_NAME.fullmatch(name) or not isinstance(record, dict)
               for name, record in state.get("removed_skills", {}).items()):
            raise ConfigError("Invalid intentional skill removal")
        if set(state.get("shared_files", {})) - {"AGENTS.md", "mcp.json"} or any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in state.get("shared_files", {}).values()):
            raise ConfigError("Invalid owned shared file")
        # Interpret pre-0.3 manifests in memory; audits never persist the upgrade.
        for key, value in state["links"].items():
            path = Path(key)
            source = self.personal / "skills" / path.name
            if str(path.parent) not in {".agents/skills", ".claude/skills", ".codex/skills"}:
                continue
            if value not in self.skill_link_values(path.name, self.home / key):
                raise ConfigError("Managed skill link points outside its shared source")
            if path.name not in state.get("skills", {}):
                # Missing legacy sources still have owned entrypoints. An unknown
                # digest can authorize unlinking those entries, never deletion of
                # a replacement source or provider copy.
                baseline = tree_digest(source) if source.is_dir() and not source.is_symlink() else "0" * 64
                record = state.setdefault("skills", {}).setdefault(path.name, {
                    "digest": state.get("tool_digest", baseline) if path.name == NAME else baseline,
                    "entrypoints": {}})
            else:
                record = state["skills"][path.name]
            if record is not None:
                record["entrypoints"].setdefault(key, value)
        return state

    def cli_lock_path(self):
        # Match Skills CLI's XDG override, but never let a fixture --home inherit
        # an unrelated user's XDG path. A recorded different path is a conflict.
        xdg = os.environ.get("XDG_STATE_HOME")
        path = Path(xdg).expanduser() / "skills/.skill-lock.json" if xdg and self.home == Path.home().resolve() else self.home / ".agents/.skill-lock.json"
        if not path.is_absolute():
            raise ConfigError("Skills CLI XDG_STATE_HOME must be absolute")
        self.safe_parent(path)
        return path

    def cli_lock(self):
        path = self.cli_lock_path()
        doc = read_json(path, None)
        if doc is not None and (doc.get("version") != 3 or not isinstance(doc.get("skills"), dict)
                                or any(not isinstance(value, dict) for value in doc["skills"].values())):
            raise ConfigError(f"Unsupported or malformed Skills CLI lockfile: {path}")
        return path, doc

    def cli_entry(self, doc, name):
        matches = []
        for key, entry in (doc or {}).get("skills", {}).items():
            normalized = re.sub(r"[^a-z0-9._]+", "-", key.lower()).strip(".-")[:255] or "unnamed-skill"
            if normalized == name:
                matches.append((key, entry))
        if len(matches) > 1:
            raise ConfigError(f"Ambiguous Skills CLI installation records: {name}")
        return matches[0] if matches else (name, None)

    def global_pending(self, state=None):
        state = state if state is not None else self.personal_state()
        path, doc = self.cli_lock()
        pending = {}
        if state.get("detached"):
            return pending
        for name, record in state.get("skills", {}).items():
            if name in state.get("removed_skills", {}):
                continue
            missing = [key for key in record["entrypoints"] if not exists(self.home / key)]
            source = self.personal / "skills" / name
            if not source.is_dir() or source.is_symlink():
                missing.append("shared source")
            cli = record.get("cli")
            if cli and cli["path"] != str(path):
                self.issue(f"Skills CLI lockfile location changed for {name}; reconcile before cleanup")
            elif cli and (doc is None or cli.get("key", name) not in doc["skills"]):
                missing.append("Skills CLI installation record")
            if missing:
                pending[name] = {"kind": "removal", "missing": missing}
        for name in state.get("removed_skills", {}):
            if any(exists(self.home / directory / name) for directory in (".agents/skills", ".claude/skills", ".codex/skills")):
                pending[name] = {"kind": "reinstall", "missing": []}
        return pending

    def record_skills(self, state, targets, blocked):
        path, doc = self.cli_lock()
        state["lifecycle_version"] = 1
        owned = state.setdefault("skills", {})
        for source in sorted((self.personal / "skills").iterdir()):
            if source.name in blocked or not SKILL_NAME.fullmatch(source.name) or not (source / "SKILL.md").is_file() or source.is_symlink():
                continue
            entries = {str((target / source.name).relative_to(self.home)): state["links"][str((target / source.name).relative_to(self.home))]
                       for target in targets if str((target / source.name).relative_to(self.home)) in state["links"]}
            if not entries:
                continue
            previous = owned.get(source.name, {})
            if previous.get("cli", {}).get("path", str(path)) != str(path):
                continue
            # Accept edited canonical content only after an explicit successful
            # reconciliation, not during audits or when provider copies conflict.
            healthy = len(entries) == len(targets) and all(
                (self.home / key).is_symlink() and os.readlink(self.home / key) == value
                for key, value in entries.items())
            record = {**previous, "digest": tree_digest(source) if healthy or not previous else previous["digest"],
                      "entrypoints": entries}
            cli_key, entry = self.cli_entry(doc, source.name)
            if entry is not None and healthy:
                record["cli"] = {"path": str(path), "key": cli_key, "entry": copy.deepcopy(entry)}
            owned[source.name] = record
        state.setdefault("removed_skills", {})

    def private_vcs(self, path: Path):
        return path.is_dir() and any(item.name in {".git", ".hg", ".svn"} for item in path.rglob("*"))

    def delete_owned(self, path: Path):
        self.safe_parent(path)
        if not exists(path):
            return
        self.changed(f"Remove owned resource: {path}")
        if self.apply:
            self.backup(path)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()

    def skill_cleanup(self, name, state, lock_path, lock_doc):
        record = state.get("skills", {}).get(name)
        source = self.personal / "skills" / name
        if (self.personal / "bin/agent-sync-config").is_file() and (self.personal / "skills/agent-sync-config/scripts/agent_sync_config.py").is_file():
            self.issue(f"Publisher source tree cannot be removed by lifecycle commands: {self.personal}")
            return []
        if record is None:
            if name in state.get("removed_skills", {}) and not exists(source):
                return []
            self.issue(f"Skill is not recorded as owned: {name}; synchronize or explicitly adopt it first")
            return []
        paths = []
        self.safe_parent(source)
        if exists(source):
            if self.private_vcs(source):
                self.issue(f"Private version-control data inside shared skill (preserved): {source}")
            elif source.is_symlink() or not source.is_dir() or tree_digest(source) != record["digest"]:
                self.issue(f"Changed shared skill source (preserved): {source}")
            else:
                paths.append(source)
        for key, expected in record["entrypoints"].items():
            target = self.home / key
            self.safe_parent(target)
            if not exists(target):
                continue
            if target.is_symlink() and os.readlink(target) == expected:
                paths.insert(0, target)
            elif target.is_dir() and not target.is_symlink() and tree_digest(target) == record["digest"]:
                paths.insert(0, target)
            else:
                self.issue(f"Changed skill entrypoint (preserved): {target}")
        cli = record.get("cli")
        if cli and cli["path"] != str(lock_path):
            self.issue(f"Skills CLI lockfile location changed (preserved): {name}")
        cli_key, entry = self.cli_entry(lock_doc, name)
        if entry is not None:
            if not cli or cli["path"] != str(lock_path) or cli.get("key", name) != cli_key or cli["entry"] != entry:
                self.issue(f"Changed or unowned Skills CLI installation record (preserved): {name}")
        return paths

    def remove_skill(self, name):
        if not SKILL_NAME.fullmatch(name):
            raise ConfigError("Skill name must use lowercase letters, numbers, and hyphens")
        if name == NAME:
            raise ConfigError("Use uninstall --scope global to remove agent-sync-config and its hooks")
        state = self.personal_state()
        lock_path, lock_doc = self.cli_lock()
        if state.get("detached"):
            self.issue("Global synchronization is detached; no skill cleanup is authorized")
            return self
        paths = self.skill_cleanup(name, state, lock_path, lock_doc)
        for path in paths:
            self.safe_parent(path)
        if self.issues:
            return self
        for path in paths:
            self.delete_owned(path)
        record = state.setdefault("skills", {}).pop(name, None)
        if record is not None:
            state.setdefault("removed_skills", {})[name] = {"digest": record["digest"]}
            for key in record["entrypoints"]:
                state["links"].pop(key, None)
            cli_key = record.get("cli", {}).get("key", name)
            if lock_doc is not None and cli_key in lock_doc["skills"]:
                del lock_doc["skills"][cli_key]
                self.write(lock_path, json_text(lock_doc), 0o600)
            state["lifecycle_version"] = 1
            self.write(self.personal / ".agent-sync.json", json_text(state), 0o600)
        return self

    def restore_skill(self, name):
        state = self.personal_state()
        source = self.personal / "skills" / name
        record = state.get("skills", {}).get(name)
        self.cli_lock()  # Validate external metadata before importing or writing.
        if name in state.get("removed_skills", {}):
            candidates = [self.home / directory / name for directory in (".agents/skills", ".claude/skills", ".codex/skills")]
            candidates = [path for path in candidates if path.is_dir() and not path.is_symlink() and (path / "SKILL.md").is_file()]
            if not candidates:
                self.issue(f"Reinstallation requires an ordinary Skills CLI source or explicit --import-skill: {name}")
                return self
            if len({tree_digest(path) for path in candidates}) != 1:
                self.issue(f"Reinstalled provider skill copies differ (preserved): {name}")
                return self
            self.import_skill(candidates[0])
            if self.issues:
                return self
            state["removed_skills"].pop(name)
            state["skills"].pop(name, None)
        elif record is not None:
            if not source.is_dir() or source.is_symlink():
                if name != NAME:
                    self.issue(f"Shared source is missing; explicitly import a replacement: {name}")
                    return self
            elif tree_digest(source) != record["digest"]:
                self.issue(f"Changed shared skill source (preserved): {source}")
                return self
            path, doc = self.cli_lock()
            cli = record.get("cli")
            if cli:
                if cli["path"] != str(path):
                    self.issue(f"Skills CLI lockfile location changed for {name}")
                    return self
                cli_key = cli.get("key", name)
                if doc is not None and cli_key in doc["skills"] and doc["skills"][cli_key] != cli["entry"]:
                    self.issue(f"Changed Skills CLI installation record (preserved): {name}")
                    return self
                doc = doc or {"version": 3, "skills": {}}
                if cli_key not in doc["skills"]:
                    doc["skills"][cli_key] = cli["entry"]
                    self.write(path, json_text(doc), 0o600)
        if self.apply:
            self.write(self.personal / ".agent-sync.json", json_text(state), 0o600)
        self.restoring.add(name)
        return self

    def uninstall(self, purge=False):
        state = self.personal_state()
        lock_path, lock_doc = self.cli_lock()
        owned = state.get("skills", {})
        runtime = self.personal / "skills" / NAME
        recovery = self.registry.get("global_uninstall")
        if not owned and not state.get("links") and not recovery:
            self.notes.append("No owned global installation to uninstall.")
            return self
        if recovery and recovery.get("purge") != purge:
            raise ConfigError("Resume the interrupted uninstall with its original --purge-shared-sources choice")
        materialize = []
        relink = []
        delete = []
        # Compute the entire plan first. A conflicting artifact blocks all edits.
        for key in (".codex/AGENTS.md", ".claude/CLAUDE.md"):
            if key not in state["links"]:
                continue
            target, source = self.home / key, self.personal / "AGENTS.md"
            self.safe_parent(source)
            expected = os.path.relpath(source, target.parent)
            if recovery and not exists(source) and target.is_file() and not target.is_symlink() and digest(target.read_bytes()) == recovery.get("state", {}).get("shared_files", {}).get("AGENTS.md"):
                continue
            if state["links"][key] != expected or not source.is_file() or source.is_symlink():
                self.issue(f"Cannot detach personal instructions: {source}")
            elif target.is_symlink() and os.readlink(target) == expected:
                materialize.append((source, target))
            elif not target.is_file() or target.is_symlink() or target.read_bytes() != source.read_bytes():
                self.issue(f"Changed instruction entrypoint (preserved): {target}")
        for name, record in owned.items():
            if name == NAME or name in state.get("removed_skills", {}):
                continue
            source = self.personal / "skills" / name
            self.safe_parent(source)
            native = self.home / ".agents/skills" / name
            if recovery and not exists(source) and native.is_dir() and not native.is_symlink() and tree_digest(native) == record["digest"]:
                source = native
            if not source.is_dir() or source.is_symlink() or tree_digest(source) != record["digest"]:
                self.issue(f"Changed or missing shared skill (preserved): {source}")
                continue
            try:
                portable_skill(source)
            except ConfigError as exc:
                self.issue(f"Cannot preserve portable native skill {source}: {exc}")
                continue
            for key, expected in record["entrypoints"].items():
                target = self.home / key
                if exists(target) and not (target.is_symlink() and os.readlink(target) in {
                        expected, os.path.relpath(native, target.parent)}):
                    if not target.is_dir() or target.is_symlink() or tree_digest(target) != record["digest"]:
                        self.issue(f"Changed skill entrypoint (preserved): {target}")
            if exists(native) and not (native.is_symlink() and os.readlink(native) == os.path.relpath(source, native.parent)):
                if not native.is_dir() or native.is_symlink() or tree_digest(native) != record["digest"]:
                    self.issue(f"Changed canonical native skill (preserved): {native}")
            materialize.append((source, native))
            for key in record["entrypoints"]:
                if key != str(native.relative_to(self.home)):
                    relink.append((self.home / key, native))
            if purge:
                if self.private_vcs(source):
                    self.issue(f"Private version-control data inside shared skill (preserved): {source}")
                delete.append(self.personal / "skills" / name)
        # Runtime removal must validate both the source and entrypoints, even when
        # npx skills has already removed some of them.
        if NAME in owned:
            delete.extend(self.skill_cleanup(NAME, state, lock_path, lock_doc))
        elif exists(runtime) and not state.get("detached"):
            self.issue(f"Setup runtime is not recorded as owned (preserved): {runtime}")
        wrapper = self.home / ".local/bin/agent-sync-config"
        expected_wrapper = state.get("wrapper_digest") or digest(self.wrapper(runtime).encode())
        if exists(wrapper):
            if wrapper.is_symlink() or not wrapper.is_file() or digest(wrapper.read_bytes()) != expected_wrapper:
                self.issue(f"Changed terminal wrapper (preserved): {wrapper}")
            else:
                delete.append(wrapper)
        hook_docs = []
        commands = self.registry.get("hook_commands", {})
        if not isinstance(commands, dict):
            raise ConfigError("Invalid recorded global hook commands")
        for provider, relative in (("codex", ".codex/hooks.json"), ("claude", ".claude/settings.json")):
            path = self.home / relative
            doc = read_json(path, {})
            if path.is_symlink():
                self.issue(f"Linked hook settings (preserved): {path}")
            hooks = doc.get("hooks", {})
            if not isinstance(hooks, dict):
                raise ConfigError(f"Expected hooks object: {path}")
            previous = commands.get(provider, [])
            if not isinstance(previous, list) or any(not isinstance(command, str) for command in previous):
                raise ConfigError("Invalid recorded hook command")
            changed = False
            for event, groups in hooks.items():
                if not isinstance(groups, list):
                    raise ConfigError(f"Expected hook groups: {path}")
                remaining_groups = []
                for group in groups:
                    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                        raise ConfigError(f"Invalid hook group: {path}")
                    remaining = []
                    group_changed = False
                    for handler in group["hooks"]:
                        if not isinstance(handler, dict):
                            raise ConfigError(f"Invalid hook handler: {path}")
                        command = handler.get("command", "")
                        if command in previous and handler.get("type") == "command":
                            changed = True
                            group_changed = True
                        else:
                            if isinstance(command, str) and str(runtime / "scripts/agent_sync_config.py") in command:
                                self.issue(f"Modified global runtime hook (preserved): {path} [{event}]")
                            remaining.append(handler)
                    if remaining or not group_changed:
                        remaining_groups.append({**group, "hooks": remaining})
                hooks[event] = remaining_groups
            if changed:
                hook_docs.append((path, doc))
        if purge:
            shared = state.get("shared_files", {})
            if not shared and state["links"]:
                shared = {"AGENTS.md": True, **({"mcp.json": True} if any(state.get("mcp", {}).values()) else {})}
            if "mcp.json" in shared and (self.personal / "mcp.json").is_file():
                neutral = read_json(self.personal / "mcp.json")
                if neutral.get("schema") != SCHEMA or not isinstance(neutral.get("servers"), dict):
                    raise ConfigError("Invalid shared MCP manifest")
                for provider, (path, doc, key) in self.mcp_documents(True).items():
                    for name, server in neutral["servers"].items():
                        actual = plain(doc.get(key, {}).get(name))
                        if provider == "claude" and isinstance(actual, dict) and "command" in actual:
                            actual = {"type": "stdio", **actual}
                        if actual != render_server(server, provider):
                            self.issue(f"Shared MCP is not preserved in native configuration: {path} [{name}]")
            for name in shared:
                source = self.personal / name
                if exists(source) and (source.is_symlink() or not source.is_file()):
                    self.issue(f"Changed shared source type (preserved): {source}")
                else:
                    delete.append(source)
        for path in [target for _, target in materialize] + [target for target, _ in relink] + delete + [path for path, _ in hook_docs]:
            self.safe_parent(path)
        if self.issues:
            return self
        # A small recovery record retains ownership until the last bundle and
        # source are gone; project registrations are never consumed by cleanup.
        if self.apply and not recovery:
            # Instructions may have changed through their shared symlink since
            # the last sync. Recovery must recognize the copies just preserved.
            for source, target in materialize:
                if source == self.personal / "AGENTS.md":
                    state.setdefault("shared_files", {})["AGENTS.md"] = digest(source.read_bytes())
            self.registry["global_uninstall"] = {"personal_root": str(self.personal), "state": copy.deepcopy(state), "purge": purge}
            self.write(self.registry_path, json_text(self.registry), 0o600)
        for source, target in materialize:
            if target.is_symlink() or not exists(target):
                self.changed(f"Preserve native copy: {source} -> {target}")
                if self.apply:
                    self.backup(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_symlink():
                        target.unlink()
                    if source.is_dir():
                        temporary = Path(tempfile.mkdtemp(prefix=".agent-sync-copy-", dir=target.parent))
                        try:
                            shutil.copytree(source, temporary, dirs_exist_ok=True)
                            if tree_digest(temporary) != tree_digest(source):
                                raise ConfigError(f"Native skill copy could not be verified: {target}")
                            os.replace(temporary, target)
                        finally:
                            if temporary.exists():
                                shutil.rmtree(temporary)
                    else:
                        self.write(target, source.read_text(), source.stat().st_mode & 0o777)
            if self.apply and ((source.is_dir() and tree_digest(target) != tree_digest(source)) or
                               (source.is_file() and target.read_bytes() != source.read_bytes())):
                raise ConfigError(f"Native copy verification failed: {target}")
        for target, native in relink:
            desired = os.path.relpath(native, target.parent)
            if target.is_symlink() and os.readlink(target) == desired:
                continue
            # Matching ordinary copies are already usable and need no conversion.
            if target.is_dir() and not target.is_symlink():
                continue
            self.changed(f"Detach provider skill link: {target} -> {desired}")
            if self.apply:
                self.backup(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                if exists(target):
                    target.unlink()
                target.symlink_to(desired)
        for path, doc in hook_docs:
            self.write(path, json_text(doc))
        tool_key = owned.get(NAME, {}).get("cli", {}).get("key", NAME)
        if lock_doc is not None and tool_key in lock_doc["skills"] and NAME in owned:
            del lock_doc["skills"][tool_key]
            self.write(lock_path, json_text(lock_doc), 0o600)
        # Keep recovery state until all sources are removed. On retry, native
        # copies are accepted above; the last executing bundle is deleted last.
        for path in dict.fromkeys(delete):
            if path != runtime:
                self.delete_owned(path)
        state["detached"] = True
        state["lifecycle_version"] = 1
        self.write(self.personal / ".agent-sync.json", json_text(state), 0o600)
        if purge:
            self.delete_owned(self.personal / ".agent-sync.json")
        cache_key = digest(("global:" + str(self.personal)).encode())[:24]
        self.delete_owned(self.state_dir / "cache" / (cache_key + ".json"))
        self.delete_owned(runtime)
        for key in ("personal_root", "hook_commands", "global_hooks_audit_only", "global_uninstall"):
            self.registry.pop(key, None)
        self.write(self.registry_path, json_text(self.registry), 0o600)
        if self.apply:
            for directory in (self.personal / "skills", self.personal):
                if directory.is_dir() and not directory.is_symlink() and not any(directory.iterdir()):
                    directory.rmdir()
        return self

    def wrapper(self, runtime):
        return "#!/bin/sh\nexec " + shlex.join([sys.executable, str(runtime / "scripts/agent_sync_config.py")]) + ' "$@"\n'

    def personal_setup(self, imported_skill=None, imported_mcp=None):
        personal_manifest_path = self.personal / ".agent-sync.json"
        state = self.personal_state()
        self.pending_removals = self.global_pending(state)
        if imported_skill:
            portable_skill(imported_skill.expanduser().resolve())
            name = imported_skill.expanduser().resolve().name
            self.import_skill(imported_skill)
            if not self.issues:
                record = state.get("skills", {}).get(name, {})
                observed = record.get("cli")
                path, doc = self.cli_lock()
                if name in self.pending_removals and observed and observed["path"] == str(path) and (doc is None or observed.get("key", name) not in doc["skills"]):
                    doc = doc or {"version": 3, "skills": {}}
                    doc["skills"][observed.get("key", name)] = observed["entry"]
                    self.write(path, json_text(doc), 0o600)
                state.setdefault("removed_skills", {}).pop(name, None)
                state.setdefault("skills", {}).pop(name, None)
                self.pending_removals.pop(name, None)
                self.restoring.add(name)
        blocked = set(state.get("removed_skills", {})) | (set(self.pending_removals) - self.restoring)
        self.pending_removals = {name: item for name, item in self.pending_removals.items() if name not in self.restoring}
        for name in sorted(self.pending_removals):
            kind = self.pending_removals[name]["kind"]
            self.issue(f"Pending skill {kind}: {name}; choose removal/uninstall or restoration during interactive global sync")
        if self.registry.get("global_uninstall"):
            self.issue("Global uninstall is interrupted; resume uninstall with its original purge choice before synchronizing")
            return
        if state.get("detached") and not self.apply:
            self.notes.append("Global synchronization is detached; explicit global sync can reattach retained sources.")
            return
        self.mkdir(self.personal)
        agents = self.personal / "AGENTS.md"
        candidates = [path for path in (self.home / ".codex/AGENTS.md", self.home / ".claude/CLAUDE.md")
                      if path.is_file() and path.resolve() != agents.resolve()]
        text = agents.read_text() if agents.exists() else candidates[0].read_text() if candidates else "# Personal agent instructions\n"
        self.write(agents, text)
        for path in (self.home / ".codex/AGENTS.md", self.home / ".claude/CLAUDE.md"):
            self.link(path, agents, state["links"], str(path.relative_to(self.home)))
        if exists(self.home / ".codex/AGENTS.override.md"):
            self.issue("Global AGENTS.override.md masks shared personal instructions in Codex")
        canonical = self.personal / "skills"
        self.mkdir(canonical)
        target = canonical / NAME
        if NAME not in blocked:
            target = self.install_runtime(canonical, state)
        targets = [self.home / ".agents/skills", self.home / ".claude/skills"]
        # Adopt legacy Codex skills without touching its .system directory.
        legacy = self.home / ".codex/skills"
        if legacy.is_dir():
            targets.append(legacy)
        self.skills(canonical, targets, state["links"], self.home, blocked)
        if not self.hook:
            self.record_skills(state, targets, blocked)
        self.mcp(self.personal / "mcp.json", state["mcp"], personal=True, imported=imported_mcp)
        if self.apply:
            self.registry["personal_root"] = str(self.personal)
        if NAME not in blocked:
            self.install_hooks()
            wrapper = self.wrapper(target)
            self.write(self.home / ".local/bin/agent-sync-config", wrapper, 0o755)
            state["wrapper_digest"] = digest(wrapper.encode())
        state.pop("detached", None)
        shared = state.setdefault("shared_files", {})
        for name in ("AGENTS.md", "mcp.json"):
            if (self.personal / name).is_file():
                shared[name] = digest((self.personal / name).read_bytes())
        if self.apply:
            self.write(personal_manifest_path, json_text(state), 0o600)

    def run(self, imported_skill: Path | None = None, imported_mcp: Path | None = None):
        if self.scope == "global":
            if self.home == Path.home().resolve():
                if os.environ.get("CODEX_HOME") and Path(os.environ["CODEX_HOME"]).expanduser().resolve() != self.home / ".codex":
                    self.issue("Nondefault CODEX_HOME is not supported by the global adapter")
                if os.environ.get("CLAUDE_CONFIG_DIR"):
                    self.issue("CLAUDE_CONFIG_DIR override is not supported by the global adapter")
            self.personal_setup(imported_skill, imported_mcp)
            if self.apply and not self.hook:
                self.write(self.registry_path, json_text(self.registry), 0o600)
            return self
        self.mkdir(self.root / ".agents")
        self.manifest["scope"] = "project"
        self.context()
        self.instructions()
        if imported_skill:
            self.import_skill(imported_skill)
        canonical = self.root / ".agents/skills"
        self.mkdir(canonical)
        if not self.hook:
            self.install_runtime(canonical, self.manifest)
            self.install_hooks()
        else:
            if not (canonical / NAME / "scripts/agent_sync_config.py").is_file():
                self.issue("Project runtime is missing; run agent-sync-config --scope project")
            if not self.apply:
                self.install_hooks()  # Audit definitions; native trust changes stay explicit.
        targets = [self.root / ".claude/skills"]
        if (self.root / ".codex/skills").is_dir():
            targets.append(self.root / ".codex/skills")
        self.skills(canonical, targets, self.manifest["links"], self.root)
        for settings in (self.root / ".claude/settings.json", self.root / ".claude/settings.local.json"):
            if read_json(settings, {}).get("disableAllHooks"):
                self.issue(f"Claude hooks are disabled by project settings (preserved): {settings}")
        self.mcp(self.root / ".agents/mcp.json", self.manifest["mcp"], imported=imported_mcp)
        self.write(self.root / ".agents/agent-sync.json", json_text(self.manifest))
        if self.apply and not self.hook:
            self.registry["projects"][str(self.root)] = {"scope": "project"}
            self.write(self.registry_path, json_text(self.registry), 0o600)
        if self.registry.get("hook_commands") and not self.registry.get("global_hooks_audit_only"):
            self.notes.append("Legacy global hooks may still repair personal resources. Upgrade them explicitly with agent-sync-config --scope global; project setup leaves them untouched.")
        return self


def stamp(path: Path):
    try:
        value = path.lstat()
        result = [value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns]
        if path.is_symlink():
            result.append(os.readlink(path))
            try:
                target = path.stat()
                result += [target.st_ino, target.st_size, target.st_mtime_ns, target.st_ctime_ns]
            except FileNotFoundError:
                result.append("broken")
        return result
    except FileNotFoundError:
        return None


def fingerprint(sync: Sync):
    if sync.scope == "project":
        paths = [sync.root / name for name in (".git", "AGENTS.md", "AGENTS.override.md", "CLAUDE.md",
                 ".claude/CLAUDE.md", ".agents/agent-sync.json", ".agents/mcp.json", ".mcp.json", ".codex/config.toml",
                 ".codex/hooks.json", ".agents/context", ".claude/context", ".codex/context",
                 ".claude/settings.json", ".claude/settings.local.json")]
        skill_dirs = [sync.root / name for name in (".agents/skills", ".claude/skills", ".codex/skills")]
    else:
        paths = [sync.registry_path, sync.personal / ".agent-sync.json", sync.personal / "AGENTS.md", sync.personal / "mcp.json", sync.cli_lock_path()]
        paths += [sync.home / name for name in (".codex/AGENTS.md", ".codex/AGENTS.override.md", ".claude/CLAUDE.md",
                  ".codex/config.toml", ".claude.json", ".codex/hooks.json", ".claude/settings.json", ".local/bin/agent-sync-config")]
        skill_dirs = [sync.personal / "skills", sync.home / ".agents/skills", sync.home / ".claude/skills", sync.home / ".codex/skills"]
    result = {str(path): stamp(path) for path in paths}
    for directory in skill_dirs:
        result[str(directory)] = stamp(directory)
        if directory.is_dir():
            for child in sorted(directory.iterdir()):
                if child.name.startswith("."):
                    continue
                result[str(child)] = stamp(child)
                result[str(child / "SKILL.md")] = stamp(child / "SKILL.md")
    return digest(json_text(result).encode())


@contextmanager
def lock(home: Path):
    directory = home / ".local/state/agent-sync-config"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "sync.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConfigError("Another synchronization is in progress; retry shortly") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def hook(args):
    event = "UserPromptSubmit"
    scope = args.scope or "project"
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ConfigError("Hook input must be an object")
        home = Path(args.home).expanduser().resolve()
        scope = args.scope or "project"  # Legacy handlers never authorize global repair.
        root = root_for(Path(payload.get("cwd", os.getcwd()))) if scope == "project" else None
        sync = Sync(home, root, False, scope=scope, hook=True)
        if scope == "project":
            registration = sync.registry.get("projects", {}).get(str(root))
            if sync.old is None or (sync.old.get("scope") != "project" and registration is None):
                return 0
        elif not (sync.personal / ".agent-sync.json").is_file():
            return 0
        # Unknown permission modes fail closed for mutation, but still audit.
        writable = payload.get("permission_mode") in {"default", "acceptEdits", "auto", "dontAsk", "bypassPermissions"}
        # Current Codex payloads omit sandbox policy, and exec can report
        # bypassPermissions even with --sandbox read-only. Never infer write access.
        if args.provider == "codex":
            writable = writable and payload.get("sandbox_mode") in {"workspace-write", "danger-full-access"}
        writable = writable and payload.get("sandbox_mode") != "read-only" and os.environ.get("AGENT_SYNC_READ_ONLY") != "1"
        writable = writable and scope == "project"
        cache_key = scope + ":" + str(root if scope == "project" else sync.personal)
        cache_path = sync.state_dir / "cache" / (digest(cache_key.encode())[:24] + ".json")
        cache = read_json(cache_path, {})
        current = fingerprint(sync)
        instruction_stamp = [stamp((root if scope == "project" else sync.personal) / "AGENTS.md")]
        event = payload.get("hook_event_name", "UserPromptSubmit")
        session = args.provider + ":" + str(payload.get("session_id", "unknown"))
        previous_instructions = cache.get("sessions", {}).get(session)
        refresh = event == "SessionStart" or previous_instructions != instruction_stamp
        if cache.get("healthy") and cache.get("fingerprint") == current:
            pass
        else:
            sync.run()
            if sync.changes and writable:
                # Audit-only handlers do not contend with project repairs.
                with lock(home):
                    Sync(home, root, True, scope="project", hook=True).run()
                    sync = Sync(home, root, False, scope="project", hook=True).run()
        messages = sync.issues + ["Synchronization required: " + change for change in sync.changes]
        if refresh:
            messages.append("Read AGENTS.md before continuing; its content may have changed. Curated .agents/context/ files are read when relevant." if scope == "project" else "Read shared personal AGENTS.md before continuing; its content may have changed.")
        if messages:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
                  "additionalContext": "agent-sync-config: " + "\n".join(messages) + f"\nUse agent-sync-config --scope {scope} to reconcile reported conflicts before unrelated work."}}))
        if os.environ.get("AGENT_SYNC_READ_ONLY") != "1":
            cache["healthy"] = not sync.issues and not sync.changes
            cache["fingerprint"] = fingerprint(sync)
            sessions = cache.setdefault("sessions", {})
            sessions[session] = instruction_stamp
            cache["sessions"] = dict(list(sessions.items())[-64:])
            sync.apply = True
            # Hooks may cache metadata outside the repo even when managed files
            # are read-only. CLI check does not write this cache or acquire a lock.
            sync.write(cache_path, json_text(cache), 0o600)
        return 0
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event,
              "additionalContext": f"agent-sync-config could not verify configuration ({type(exc).__name__}). Run agent-sync-config check --scope {scope} and resolve it before unrelated work."}}))
        return 0


def confirm_changes(result, args):
    if not result.changes or args.yes:
        return True
    if args.json or not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ConfigError("Confirmation required: review --dry-run, then use --yes for noninteractive cleanup")
    for change in result.changes:
        print(change)
    try:
        return input("Apply this cleanup? [y/N]: ").strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False


def lifecycle_operation(operation, args):
    return operation.remove_skill(args.skill_name) if args.action == "remove-skill" else operation.uninstall(args.purge_shared_sources)


def lifecycle_execute(home, args):
    preview = lifecycle_operation(Sync(home, None, False, args.personal_root, scope="global"), args)
    if preview.issues or args.dry_run or args.read_only:
        return preview
    if not confirm_changes(preview, args):
        preview.changes.clear()
        preview.notes.append("Cancelled; no changes made.")
        return preview
    if not preview.changes:
        return preview
    with lock(home):
        return lifecycle_operation(Sync(home, None, True, args.personal_root, scope="global"), args)


def interactive_removals(home, args):
    probe = Sync(home, None, False, args.personal_root, scope="global")
    pending = probe.global_pending()
    if not pending or args.json or not sys.stdin.isatty() or not sys.stdout.isatty():
        return [], False
    choices = []
    for name, item in sorted(pending.items(), key=lambda item: (item[0] != NAME, item[0])):
        if args.import_skill and name == args.import_skill.expanduser().resolve().name:
            continue
        remove_label = "Uninstall synchronizer (keep native configuration)" if name == NAME else "Complete removal of the shared source"
        restore_label = "Accept reinstallation" if item["kind"] == "reinstall" else "Restore installation"
        print(f"Pending {item['kind']}: {name}\n1. {remove_label}\n2. {restore_label}\nq. Cancel")
        try:
            choice = input("Choose [1/2/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "q"
        if choice in {"", "q", "cancel"}:
            return [], True
        if choice not in {"1", "2"}:
            raise ConfigError("Choose removal, restoration, or cancellation; no changes made")
        choices.append((name, choice == "1"))
        if name == NAME and choice == "1":
            # Full uninstall keeps all remaining native configuration; there is
            # no reason to ask about separate skill decisions afterward.
            return choices, False
    return choices, False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("sync", "check", "hook", "remove-skill", "uninstall"), default="sync")
    parser.add_argument("skill_name", nargs="?", help="Owned skill to remove")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writes or locks")
    parser.add_argument("--yes", action="store_true", help="Confirm an explicit cleanup; does not resolve ambiguous removals")
    parser.add_argument("--purge-shared-sources", action="store_true", help="Uninstall and delete redundant owned personal sources")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--scope", choices=("project", "global"), action="append", help="Select project or global resources exclusively")
    parser.add_argument("--project", type=Path, help="Project directory (default: current directory); project scope only")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Home override for isolated tests")
    parser.add_argument("--personal-root", type=Path, help="Personal source directory; global scope only")
    parser.add_argument("--project-only", action="store_true", help="Alias for --scope project")
    parser.add_argument("--read-only", action="store_true", help="Same behavior as check")
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report without interactive prompts")
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    parser.add_argument("--import-skill", type=Path, help="Adopt a self-contained skill into the selected scope")
    parser.add_argument("--import-mcp", type=Path, help="Adopt Claude-format mcpServers into the selected scope")
    args = parser.parse_args(argv)
    scope, root, selection_required = args.scope[-1] if args.scope else None, None, False
    apply = args.action != "check" and not args.read_only and not args.dry_run
    try:
        if args.scope and len(set(args.scope)) > 1:
            raise ConfigError("Contradictory --scope values; choose project or global")
        if args.project_only:
            if scope == "global":
                raise ConfigError("--project-only contradicts --scope global")
            scope = "project"
        if scope == "global" and args.project is not None:
            raise ConfigError("--project cannot be used with --scope global")
        if args.personal_root and scope != "global":
            raise ConfigError("--personal-root requires --scope global")
        destructive = args.action in {"remove-skill", "uninstall"}
        if destructive:
            if scope != "global" or args.project_only:
                raise ConfigError("Global lifecycle commands require explicit --scope global")
            if args.import_skill or args.import_mcp:
                raise ConfigError("Lifecycle commands do not accept imports")
            if args.action == "remove-skill" and not args.skill_name:
                raise ConfigError("remove-skill requires a skill name")
        if args.skill_name and args.action != "remove-skill":
            raise ConfigError("A skill name is only accepted by remove-skill")
        if args.purge_shared_sources and args.action != "uninstall":
            raise ConfigError("--purge-shared-sources requires uninstall --scope global")
        if args.action == "hook" and (args.dry_run or args.yes):
            raise ConfigError("Hook handlers do not accept lifecycle flags")
        if args.action == "hook":
            args.scope = scope
            return hook(args)
        home = args.home.expanduser().resolve()
        if scope != "global":
            root = root_for(args.project or Path.cwd())
        if scope is None:
            if not apply or project_config_exists(root):
                scope = "project"
            elif args.json or not sys.stdin.isatty() or not sys.stdout.isatty():
                selection_required = True
                raise ConfigError("Scope selection required: choose --scope project to initialize this project, or --scope global to synchronize personal resources")
            else:
                print("No project agent configuration found.\n1. Initialize this project\n2. Synchronize global configuration\nq. Cancel")
                try:
                    choice = input("Choose a scope [1/2/q]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    choice = "q"
                if choice in ("", "q", "cancel"):
                    print("Cancelled; no changes made.")
                    return 0
                scope = {"1": "project", "project": "project", "2": "global", "global": "global"}.get(choice)
                if scope is None:
                    raise ConfigError("Choose project or global scope; no changes made")
                if scope == "global" and args.project is not None:
                    raise ConfigError("Global scope does not accept --project; rerun with --scope global")
        if scope == "global":
            root = None
        # Validate target/manifest before creating runtime state or acquiring a lock.
        if destructive:
            result = lifecycle_execute(home, args)
        else:
            choices, cancelled = interactive_removals(home, args) if scope == "global" and apply else ([], False)
            operation = Sync(home, root, apply, args.personal_root, scope=scope)
            if cancelled:
                result = operation
                result.notes.append("Cancelled; no changes made.")
            elif apply:
                previews = []
                for name, remove in choices:
                    preview = Sync(home, None, False, args.personal_root, scope="global")
                    preview.uninstall() if remove and name == NAME else preview.remove_skill(name) if remove else preview.restore_skill(name)
                    previews.append((preview, remove))
                blocked = next((preview for preview, _ in previews if preview.issues), None)
                confirmed = blocked is None and all(not remove or confirm_changes(preview, args) for preview, remove in previews)
                if blocked is not None:
                    result = blocked
                elif not confirmed:
                    result = operation
                    result.notes.append("Cancelled; no changes made.")
                else:
                    with lock(home):
                        result = operation
                        uninstalled = False
                        for name, remove in choices:
                            if remove and name == NAME:
                                result = operation.uninstall()
                                uninstalled = True
                                break
                            operation.remove_skill(name) if remove else operation.restore_skill(name)
                            if operation.issues:
                                break
                        if not uninstalled and not operation.issues:
                            result = operation.run(args.import_skill, args.import_mcp)
            else:
                result = operation.run(args.import_skill, args.import_mcp)
        report = {"version": VERSION, "scope": scope, "project": str(root) if root else None,
                  "read_only": not apply, "changes": result.changes, "issues": result.issues, "notes": result.notes,
                  "pending_removals": result.pending_removals}
        if args.json:
            print(json_text(report), end="")
        else:
            print(f"Scope: {scope}" + (f" ({root})" if root else ""))
            for kind, entries in (("CONFLICT", result.issues), ("CHANGE" if apply else "DRIFT", result.changes), ("NOTE", result.notes)):
                for message in entries:
                    print(f"{kind}: {message}")
            if not result.issues and not result.changes:
                print("Configuration is synchronized.")
        return 1 if result.issues or (not apply and result.changes and not args.dry_run) else 0
    except (ConfigError, OSError, ValueError, TypeError, KeyError) as exc:
        # Never print configuration contents or resolved environment values on error.
        message = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
        if args.json:
            print(json_text({"error": message, "scope": scope, "selection_required": selection_required}), end="")
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        sys.exit("agent-sync-config requires Python 3.11 or later")
    sys.exit(main())
