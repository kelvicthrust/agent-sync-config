#!/usr/bin/env python3
"""Share local agent configuration without overwriting conflicting content."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_resources

VERSION = "0.6.0"
NAME = "agent-sync-config"
BEGIN = "<!-- agent-sync-config:start -->"
END = "<!-- agent-sync-config:end -->"
GUIDANCE = f"""{BEGIN}
## Shared agent configuration

Edit project instructions in AGENTS.md and shared skills in .agents/skills/.
Reference existing context documents here; no separate context store is needed.
Claude reads these instructions through CLAUDE.md and skills through relative links.

Use the installed agent-sync-config skill to check or synchronize this project:
Claude Code: /agent-sync-config. Codex: $agent-sync-config or select it with @.
Request a check for read-only verification. Project sync uses --scope project;
personal configuration requires an explicit --scope global request.
MCP uses native .mcp.json and .codex/config.toml. Differing definitions require
an explicit --mcp-source codex or --mcp-source claude choice.

The tool installs no runtime, hooks, launcher, or persistent state here.
Use your skill installer for installation, updates, and removal. Explicit sync
can repair missing references; it does not remember previous removal decisions.
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
    """Compare current skill contents, including relative dependency links."""
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


def portable_skill(source: Path):
    if not SKILL_NAME.fullmatch(source.name) or not (source / "SKILL.md").is_file():
        raise ConfigError("Skill directory needs a lowercase hyphenated name and SKILL.md")
    for path in source.rglob("*"):
        if path.name in {".git", ".hg", ".svn"}:
            raise ConfigError("Skill contains private version-control data; preserve it outside the adopted skill")
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
    """Change explicitly selected portable keys while retaining comments."""
    for key in list(table):
        if key not in desired:
            del table[key]
    for key, value in desired.items():
        if isinstance(value, dict) and key in table and isinstance(plain(table[key]), dict):
            update_toml_table(table[key], value)
        else:
            table[key] = value


def root_for(path: Path) -> Path:
    """Find the Git/worktree root; non-Git directories remain explicit targets."""
    path = path.expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(f"Project directory does not exist: {path}")
    for candidate in (path, *path.parents):
        if exists(candidate / ".git"):
            return candidate
    return path


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
    if "env_vars" in result:
        result["env_vars"] = sorted(set(result["env_vars"]))
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
    def __init__(self, home: Path, root: Path | None, apply: bool, scope="project"):
        self.home, self.root, self.apply, self.scope = home, root, apply, scope
        self.base = home if scope == "global" else root
        self.issues, self.changes, self.notes = [], [], []
        self.resources, self.references = [], []
        self.edits = []
        self.observed = {}
        if scope == "project" and (root == home or exists(root / ".agent-sync.json") or any(root.is_relative_to(home / name)
                for name in (".agents", ".claude", ".codex", "agent-config"))):
            raise ConfigError("Choose a project outside personal/global configuration, or use --scope global")
        if scope == "global" and home == Path.home().resolve():
            if os.environ.get("CODEX_HOME") and Path(os.environ["CODEX_HOME"]).expanduser().resolve() != home / ".codex":
                raise ConfigError("Nondefault CODEX_HOME is not supported by the global adapter")
            if os.environ.get("CLAUDE_CONFIG_DIR"):
                raise ConfigError("CLAUDE_CONFIG_DIR override is not supported by the global adapter")

    def issue(self, message):
        if message not in self.issues:
            self.issues.append(message)

    def safe_parent(self, path):
        if not path.is_relative_to(self.base):
            raise ConfigError(f"Refusing to write outside {self.scope} scope: {path}")
        for parent in path.parents:
            if parent == self.base:
                break
            if parent.is_symlink():
                raise ConfigError(f"Refusing to write through a linked configuration directory: {parent}")
            if exists(parent) and not parent.is_dir():
                raise ConfigError(f"Configuration parent is not a directory: {parent}")

    def fingerprint(self, path):
        if not exists(path):
            return None
        mode = path.lstat().st_mode
        if path.is_symlink():
            return mode, os.readlink(path)
        if path.is_dir():
            return mode, tree_digest(path)
        return mode, digest(path.read_bytes())

    def observe(self, path):
        self.observed.setdefault(path, self.fingerprint(path))

    def edit(self, kind, path, value, message):
        self.safe_parent(path)
        self.observe(path)
        self.edits.append((kind, path, value))
        self.changes.append(message)

    def write(self, path, text):
        self.safe_parent(path)
        self.observe(path)
        if path.is_symlink():
            self.issue(f"Externally linked configuration (preserved): {path}; reconcile its source explicitly")
        elif exists(path) and not path.is_file():
            raise ConfigError(f"Expected a configuration file: {path}")
        elif not path.exists() or path.read_text() != text:
            self.edit("write", path, text, f"Update: {path}")

    def link(self, target, source, comparison=None):
        self.safe_parent(target)
        self.observe(target)
        comparison = comparison or source
        self.observe(comparison)
        if target.is_symlink():
            if target.resolve() == source.resolve():
                return
            self.issue(f"Conflicting symlink (preserved): {target}")
            return
        if exists(target):
            same = (target.is_file() and comparison.is_file() and target.read_bytes() == comparison.read_bytes()) or (
                target.is_dir() and comparison.is_dir() and tree_digest(target) == tree_digest(comparison))
            if not same:
                self.issue(f"Conflicting content (preserved): {target}")
                return
            if target.is_dir():
                try:
                    portable_skill(target)
                except ConfigError as exc:
                    self.issue(f"Cannot replace skill copy {target}: {exc}")
                    return
        self.edit("link", target, source, f"Link: {target} -> {os.path.relpath(source, target.parent)}")

    def instructions(self):
        if self.scope == "global":
            agents, claude = self.home / ".codex/AGENTS.md", self.home / ".claude/CLAUDE.md"
            self.safe_parent(agents)
            self.safe_parent(claude)
            self.observe(agents); self.observe(claude)
            if agents.is_symlink():
                self.issue(f"Externally linked global instructions (preserved): {agents}; materialize native instructions explicitly")
                return
            if exists(agents) and not agents.is_file():
                raise ConfigError(f"Expected instruction file: {agents}")
            if claude.is_symlink() and claude.resolve() != agents.resolve():
                self.issue(f"Externally linked Claude instructions (preserved): {claude}")
                return
            if exists(claude) and not claude.is_file():
                raise ConfigError(f"Expected instruction file: {claude}")
            wrapper = "@../.codex/AGENTS.md"
            imported_wrapper = claude.is_file() and not claude.is_symlink() and claude.read_text().strip() == wrapper
            if imported_wrapper and not agents.is_file():
                self.issue(f"Missing shared global instruction source (preserved): {agents}")
                return
            text = agents.read_text() if agents.exists() else claude.read_text() if claude.is_file() else "# Personal agent instructions\n"
            if claude.is_file() and agents.is_file() and not imported_wrapper and claude.read_text() != text:
                self.issue(f"Personal instructions differ (preserved): {agents}, {claude}")
                return
            self.adapter.record(claude, "shared-native", "Native global instructions share one source", agents)
            self.write(agents, claude_resources.add_references(text, self.references))
            if not imported_wrapper:
                self.link(claude, agents, comparison=agents if agents.exists() else claude)
            if exists(self.home / ".codex/AGENTS.override.md"):
                self.issue("Global AGENTS.override.md takes precedence over shared AGENTS.md; reconcile explicitly")
            return
        agents = self.root / "AGENTS.md"
        self.observe(agents)
        if agents.is_symlink():
            self.issue(f"Externally linked project instructions (preserved): {agents}")
            return
        if exists(agents) and not agents.is_file():
            raise ConfigError(f"Expected instruction file: {agents}")
        text = agents.read_text() if agents.exists() else None
        candidates = []
        for path, wrapper in ((self.root / "CLAUDE.md", "@AGENTS.md"),
                              (self.root / ".claude/CLAUDE.md", "@../AGENTS.md")):
            self.safe_parent(path)
            self.observe(path)
            if not exists(path):
                continue
            if path.is_symlink():
                if path.resolve() == agents.resolve():
                    continue
                self.issue(f"Externally linked instruction file (preserved): {path}")
                return
            if not path.is_file():
                raise ConfigError(f"Expected instruction file: {path}")
            content = path.read_text()
            if content.strip() != wrapper:
                candidates.append((path, content, wrapper))
        text = text if text is not None else candidates[0][1] if candidates else "# Project instructions\n\nAdd project conventions and build/test commands here.\n"
        before = len(self.issues)
        for path, content, _ in candidates:
            if strip_guidance(claude_resources.strip_references(content)) != strip_guidance(claude_resources.strip_references(text)):
                self.issue(f"Instructions differ from AGENTS.md (preserved): {path}")
        if len(self.issues) != before:
            return
        for path, _, _ in candidates:
            self.adapter.record(path, "shared-native", "Compatible Claude instructions adopted; native import wrapper shares AGENTS.md", agents)
        self.write(agents, claude_resources.add_references(add_guidance(text), self.references))
        claude = self.root / "CLAUDE.md"
        if not exists(claude) or (not claude.is_symlink() and claude.read_text().strip() == "@AGENTS.md"):
            self.write(claude, "@AGENTS.md\n")
        for path, _, wrapper in candidates:
            self.write(path, wrapper + "\n")
        if exists(self.root / "AGENTS.override.md"):
            self.issue("AGENTS.override.md takes precedence over root AGENTS.md; reconcile explicitly")

    def skills(self, imported=None):
        canonical = self.base / ".agents/skills"
        provider = self.base / ".claude/skills"
        for directory in (canonical, provider):
            self.safe_parent(directory / "placeholder")
            if exists(directory) and not directory.is_dir():
                raise ConfigError(f"Expected skill directory: {directory}")
        sources = {}
        if canonical.is_dir():
            for source in sorted(canonical.iterdir()):
                if source.name == NAME or source.name.startswith("."):
                    continue
                if not SKILL_NAME.fullmatch(source.name) or not (source / "SKILL.md").is_file():
                    self.issue(f"Invalid shared skill directory (preserved): {source}")
                    continue
                if source.is_symlink():
                    self.issue(f"Externally linked shared skill (preserved): {source}; explicitly reconcile its source")
                    continue
                if (source / "SKILL.md").is_symlink():
                    self.issue(f"Externally linked shared skill instructions (preserved): {source / 'SKILL.md'}")
                    continue
                self.observe(source)
                sources[source.name] = source
                self.adapter.record(source, "shared-native", "Agent Skill shared through native discovery", provider / source.name)
        if imported:
            source = imported.expanduser().resolve()
            if source.name == NAME:
                raise ConfigError("Install agent-sync-config with your skill installer; the synchronizer never imports itself")
            portable_skill(source)
            self.observe(source)
            target = canonical / source.name
            if exists(target):
                if target.is_symlink() or tree_digest(target) != tree_digest(source):
                    self.issue(f"Imported skill conflicts (preserved): {target}")
            else:
                self.edit("copy", target, source, f"Import skill: {source} -> {target}")
                sources[source.name] = source
        if provider.is_dir():
            for item in sorted(provider.iterdir()):
                if item.name == NAME or item.name.startswith(".") or item.name in {"synced", "anthropic-skills"}:
                    continue
                target = canonical / item.name
                if item.is_symlink() and not item.exists():
                    self.issue(f"Dangling skill reference (preserved): {item}; remove it explicitly or reinstall the skill")
                    continue
                if not (item / "SKILL.md").is_file() or item.name in sources:
                    continue
                if exists(target) or item.is_symlink():
                    self.issue(f"External skill link needs explicit reconciliation: {item}")
                    continue
                limitation = claude_resources.skill_limitation((item / "SKILL.md").read_text())
                if limitation:
                    self.adapter.reference(item / "SKILL.md", "Skill", limitation)
                    continue
                try:
                    portable_skill(item)
                except ConfigError as exc:
                    self.issue(f"Cannot adopt skill {item}: {exc}")
                    continue
                self.observe(item)
                self.edit("move", target, item, f"Adopt skill: {item} -> {target}")
                sources[item.name] = item
                self.adapter.record(item, "shared-native", "Portable Agent Skill adopted with its supporting files", target)
        for name, comparison in sources.items():
            target = provider / name
            # Adoption moves this ordinary directory first, then installs its reference.
            if comparison == target:
                self.edit("link", target, canonical / name, f"Link: {target} -> {os.path.relpath(canonical / name, target.parent)}")
            else:
                self.link(target, canonical / name, comparison)

    def mcp(self, selected=None, imported=None):
        personal = self.scope == "global"
        paths = {"codex": self.base / ".codex/config.toml",
                 "claude": self.home / ".claude.json" if personal else self.root / ".mcp.json"}
        docs, servers = {}, {}
        for provider, path in paths.items():
            self.safe_parent(path)
            self.observe(path)
            docs[provider] = read_toml(path) if provider == "codex" else read_json(path, {})
            key = "mcp_servers" if provider == "codex" else "mcpServers"
            servers[provider] = plain(docs[provider].get(key, {}))
            if not isinstance(servers[provider], dict):
                raise ConfigError(f"Expected MCP server map: {path}")
        extra = {}
        if imported:
            imported = imported.expanduser().resolve()
            self.observe(imported)
            if not imported.is_file():
                raise ConfigError("Imported MCP file must exist and contain native mcpServers")
            extra = read_json(imported).get("mcpServers")
            if not isinstance(extra, dict):
                raise ConfigError("Imported MCP file must contain native mcpServers")
        updates = {"codex": {}, "claude": {}}
        for name in sorted(set(servers["codex"]) | set(servers["claude"]) | set(extra)):
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ConfigError("MCP names must use letters, digits, underscores, or hyphens")
            values = {}
            try:
                for provider in ("codex", "claude"):
                    if name in servers[provider]:
                        values[provider] = import_server(servers[provider][name], provider)
                if name in extra:
                    wanted = import_server(extra[name], "claude")
                elif len(values) == 2 and values["codex"] != values["claude"]:
                    if not selected:
                        self.issue(f"MCP definitions differ (preserved): {name}; choose --mcp-source codex or --mcp-source claude")
                        continue
                    wanted = values[selected]
                else:
                    wanted = next(iter(values.values()))
                rendered = {provider: render_server(wanted, provider) for provider in ("codex", "claude")}
            except ConfigError as exc:
                self.issue(f"Cannot share MCP {name} (native definitions preserved): {exc}")
                continue
            for provider in ("codex", "claude"):
                if values.get(provider) != wanted:
                    updates[provider][name] = rendered[provider]
        for provider in ("codex", "claude"):
            if not updates[provider]:
                continue
            doc = docs[provider]
            key = "mcp_servers" if provider == "codex" else "mcpServers"
            if key not in doc:
                doc[key] = toml_module().table() if provider == "codex" else {}
            for name, value in updates[provider].items():
                if provider == "codex" and name in doc[key]:
                    update_toml_table(doc[key][name], value)
                else:
                    doc[key][name] = value
            self.write(paths[provider], toml_module().dumps(doc) if provider == "codex" else json_text(doc))
            self.notes.append(f"MCP changed for {provider}; reconnect servers or restart that client if necessary.")

    def legacy(self):
        paths = (self.home / "agent-config", self.home / ".local/state/agent-sync-config",
                 self.home / ".local/bin/agent-sync-config") if self.scope == "global" else (
                 self.root / ".agents/agent-sync.json", self.root / ".agents/mcp.json")
        for path in paths:
            if exists(path):
                self.issue(f"Legacy synchronizer resource (preserved): {path}; reconcile native replacements and clean up explicitly")
        legacy_skills = self.base / ".codex/skills"
        if legacy_skills.is_dir():
            for item in sorted(legacy_skills.iterdir()):
                if item.name == NAME or item.name.startswith("."):
                    continue
                self.issue(f"Legacy Codex skill entrypoint (preserved): {item}; use .agents/skills and remove obsolete aliases explicitly")
        for relative in (".claude/settings.json", ".claude/settings.local.json", ".codex/hooks.json"):
            path = self.base / relative
            self.safe_parent(path)
            doc = read_json(path, {})
            hooks = doc.get("hooks", {})
            if not isinstance(hooks, dict):
                raise ConfigError(f"Expected native hooks object: {path}")
            for groups in hooks.values():
                if not isinstance(groups, list):
                    raise ConfigError(f"Expected native hook groups: {path}")
                for group in groups:
                    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                        raise ConfigError(f"Invalid native hook group: {path}")
                    for handler in group["hooks"]:
                        if not isinstance(handler, dict):
                            raise ConfigError(f"Invalid native hook handler: {path}")
                        command = handler.get("command", "")
                        if isinstance(command, str) and "agent_sync_config.py" in command and "hook" in command:
                            self.issue(f"Legacy synchronizer hook (preserved): {path}; remove this handler explicitly without changing unrelated hooks")

    def run(self, imported_skill=None, imported_mcp=None, mcp_source=None):
        if imported_skill:
            source = imported_skill.expanduser().resolve()
            if source.name == NAME:
                raise ConfigError("Install agent-sync-config with your skill installer; the synchronizer never imports itself")
            portable_skill(source)
        self.legacy()
        self.mcp(mcp_source, imported_mcp)  # Parse native formats before planning instruction/skill edits.
        self.adapter = claude_resources.Resources(self, ConfigError, exists, toml_module)
        self.skills(imported_skill)
        self.references = self.adapter.run()
        self.instructions()
        if self.apply:
            self.commit()
        return self

    def commit(self):
        for path, previous in self.observed.items():
            if self.fingerprint(path) != previous:
                raise ConfigError(f"Configuration changed during preflight; rerun sync: {path}")
        for kind, path, value in self.edits:
            self.safe_parent(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if kind == "write":
                mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                    temp = Path(stream.name)
                    stream.write(value.encode())
                try:
                    temp.chmod(mode)
                    os.replace(temp, path)
                finally:
                    temp.unlink(missing_ok=True)
            elif kind == "move":
                value.rename(path)
            elif kind == "copy":
                shutil.copytree(value, path)
            elif kind == "retire-command":
                replacement, entry, content, original = value
                if path.is_symlink() or path.read_bytes() != original or replacement.read_text() != content or not entry.is_symlink() or entry.resolve() != replacement.parent.resolve():
                    raise ConfigError(f"Command replacement could not be verified; original preserved: {path}")
                path.unlink()
            else:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                elif exists(path):
                    path.unlink()
                path.symlink_to(os.path.relpath(value, path.parent))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("sync", "check", "hook", "remove-skill", "uninstall"), default="sync",
                        help="sync or check native sharing and Claude resource adaptations; hook is a retired no-op")
    parser.add_argument("skill_name", nargs="?", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--scope", choices=("project", "global"), action="append", help="Select project or global resources exclusively")
    parser.add_argument("--project", type=Path, help="Project directory; defaults to current directory")
    parser.add_argument("--home", type=Path, default=Path.home(), help="Home override for isolated tests")
    parser.add_argument("--project-only", action="store_true", help="Alias for --scope project")
    parser.add_argument("--read-only", action="store_true", help="Same behavior as check")
    parser.add_argument("--dry-run", action="store_true", help="Preview native changes without writes")
    parser.add_argument("--json", action="store_true", help="Machine-readable report; never prompt")
    parser.add_argument("--import-skill", type=Path, help="Adopt an ordinary self-contained skill into the selected scope")
    parser.add_argument("--import-mcp", type=Path, help="Import native Claude-format mcpServers into the selected scope")
    parser.add_argument("--mcp-source", choices=("codex", "claude"), help="Explicitly resolve differing portable native MCP definitions")
    parser.add_argument("--personal-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--purge-shared-sources", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--provider", choices=("codex", "claude"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    scope, root, selection_required = args.scope[-1] if args.scope else None, None, False
    apply = args.action != "check" and not args.read_only and not args.dry_run
    try:
        if args.action == "hook":
            return 0
        if args.action in {"remove-skill", "uninstall"} or args.purge_shared_sources or args.yes:
            raise ConfigError("Lifecycle commands are retired. Use your skill installer (npx skills remove) for removal; inspect and reconcile legacy configuration explicitly. No files changed.")
        if args.personal_root:
            raise ConfigError("--personal-root is retired; use native configuration locations. Existing custom sources remain untouched.")
        if args.skill_name or args.provider:
            raise ConfigError("Unexpected positional argument or retired --provider option")
        if args.scope and len(set(args.scope)) > 1:
            raise ConfigError("Contradictory --scope values; choose project or global")
        if args.project_only:
            if scope == "global":
                raise ConfigError("--project-only contradicts --scope global")
            scope = "project"
        if scope == "global" and args.project is not None:
            raise ConfigError("--project cannot be used with --scope global")
        if args.import_mcp and args.mcp_source:
            raise ConfigError("Choose --import-mcp or --mcp-source, not both")
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
        result = Sync(home, root, apply, scope).run(args.import_skill, args.import_mcp, args.mcp_source)
        report = {"version": VERSION, "scope": scope, "project": str(root) if root else None,
                  "read_only": not apply, "changes": result.changes, "issues": result.issues, "notes": result.notes, "resources": result.resources}
        if args.json:
            print(json_text(report), end="")
        else:
            print(f"Scope: {scope}" + (f" ({root})" if root else ""))
            for kind, entries in (("CONFLICT", result.issues), ("CHANGE" if apply else "DRIFT", result.changes), ("NOTE", result.notes)):
                for message in entries:
                    print(f"{kind}: {message}")
            for resource in result.resources:
                print(f"RESOURCE [{resource['disposition']}]: {resource['source']}: {resource['compatibility']}")
            if not result.issues and not result.changes:
                print("Configuration is synchronized.")
        return 1 if result.issues or (not apply and result.changes and not args.dry_run) else 0
    except (ConfigError, OSError, ValueError, TypeError, KeyError) as exc:
        message = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
        if args.json:
            print(json_text({"error": message, "scope": scope, "selection_required": selection_required}), end="")
        else:
            print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if sys.version_info < (3, 9):
        sys.exit("agent-sync-config requires Python 3.9 or later")
    sys.exit(main())
