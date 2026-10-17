"""Read two local configuration values without executing shell code or logging keys."""
from pathlib import Path
import shlex


class ConfigError(ValueError):
    pass


def read_config(path):
    try:
        lines = Path(path).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError) as error:
        raise ConfigError('Cannot read Gemini configuration file.') from error
    values = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        name, separator, raw = line.partition('=')
        name = name.strip()
        if not separator or name not in {'GEMINI_API_KEY', 'GEMINI_MODEL'} or name in values:
            raise ConfigError('Use one GEMINI_API_KEY and optional GEMINI_MODEL assignment only.')
        try:
            tokens = shlex.split(raw, comments=True)
        except ValueError as error:
            raise ConfigError('Invalid quoting in Gemini configuration.') from error
        if len(tokens) > 1:
            raise ConfigError('Gemini configuration values must be single strings.')
        values[name] = tokens[0] if tokens else ''
    return values
