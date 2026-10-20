import os
import re
import subprocess
from pathlib import Path

import yaml


_ENVIRONMENT_VARIABLE = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def _expand_value(value):
    if isinstance(value, str):
        value = _ENVIRONMENT_VARIABLE.sub(
            lambda match: os.environ.get(match.group(1), match.group(2) or match.group(0)),
            value,
        )
        return os.path.expanduser(os.path.expandvars(value))
    if isinstance(value, list):
        return [_expand_value(item) for item in value]
    return value


def load_surfex_configuration(config_path, platform, experiment):
    with open(config_path, "r", encoding="utf-8") as config_file:
        configuration = yaml.safe_load(config_file) or {}

    general = configuration.get("general", {})
    platform_settings = configuration.get("platforms", {}).get(platform, {})
    experiment_settings = configuration.get(experiment, {})
    for section_name, section in (
        ("general", general),
        (f"platforms.{platform}", platform_settings),
        (experiment, experiment_settings),
    ):
        if not isinstance(section, dict):
            raise ValueError(f"SURFEX configuration section '{section_name}' must be a mapping")

    settings = {**general, **platform_settings, **experiment_settings}
    required_settings = ("surfex_home", "surfex_profile", "surfex_exe", "paramfiles")
    missing_settings = [key for key in required_settings if not settings.get(key)]
    if missing_settings:
        raise ValueError(
            f"SURFEX configuration is missing required settings: {', '.join(missing_settings)}"
        )

    settings.setdefault("physiography_paths", [])
    settings = {key: _expand_value(value) for key, value in settings.items()}
    surfex_home = settings["surfex_home"]
    for key in ("surfex_exe", "paramfiles"):
        if not os.path.isabs(settings[key]):
            settings[key] = os.path.join(surfex_home, settings[key])
    return settings


def load_surfex_environment(surfex_home, surfex_profile, surfex_exe, base_environment):
    profile_path = os.path.join(surfex_home, "conf", surfex_profile)
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; env', "surfex-profile", profile_path],
        env=base_environment,
        capture_output=True,
        text=True,
        check=True,
    )
    environment = base_environment.copy()
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            environment[key] = value

    if not environment.get("PATH", "").startswith(f"{surfex_exe}:"):
        environment["PATH"] = f"{surfex_exe}:{environment.get('PATH', '')}"
    return environment


def resolve_surfex_executable(surfex_exe, executable):
    executable_path = Path(surfex_exe) / executable
    if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
        raise FileNotFoundError(
            f"Configured SURFEX executable for {executable} is missing or not executable: "
            f"{executable_path}"
        )
    return str(executable_path.resolve())