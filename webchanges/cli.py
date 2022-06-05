#!/usr/bin/env python3

"""Module containing the entry point: the function main()."""

# See config module for the command line arguments.

# The code below is subject to the license contained in the LICENSE file, which is part of the source code.

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import warnings
from pathlib import Path, PurePath
from typing import Optional

import platformdirs

from . import __copyright__, __docs_url__, __min_python_version__, __project_name__, __version__
from .config import CommandConfig
from .util import get_new_version_number

# Ignore signal SIGPIPE ("broken pipe") for stdout (see https://github.com/thp/urlwatch/issues/77)
if sys.platform != 'win32':  # Windows does not have signal.SIGPIPE
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # type: ignore[attr-defined]  # not defined in Windows

logger = logging.getLogger(__name__)


def python_version_warning() -> None:
    """Check if we're running on the minimum Python version supported and if so print and issue a pending deprecation
    warning."""
    if sys.version_info[0:2] == __min_python_version__:
        current_minor_version = '.'.join(str(n) for n in sys.version_info[0:2])
        next_minor_version = f'{__min_python_version__[0]}.{__min_python_version__[1] + 1}'
        warning = (
            f'Support for Python {current_minor_version} will be ending three years from the date Python '
            f'{next_minor_version} was released'
        )
        print(f'WARNING: {warning}\n')
        PendingDeprecationWarning(warning)


def migrate_from_legacy(
    legacy_package: str, config_file: Path, jobs_file: Path, hooks_file: Path, cache_file: Path
) -> None:
    """Check for existence of legacy files for configuration, jobs and Python hooks and migrate them (i.e. make a copy
    to new folder and/or name). Original files are not deleted.

    :param legacy_package: The name of the legacy package to migrate (e.g. urlwatch).
    :param config_file: The Path to the configuration file.
    :param jobs_file: The Path to the jobs file.
    :param hooks_file: The Path to the hooks file.
    :param cache_file: The Path to the snapshot database file.
    """
    lg_project_path = Path.home().joinpath(f'.{legacy_package}')
    lg_config_file = lg_project_path.joinpath(f'{legacy_package}.yaml')
    lg_urls_file = lg_project_path.joinpath('urls.yaml')
    lg_hooks_file = lg_project_path.joinpath('hooks.py')
    lg_cache_path = platformdirs.user_cache_path(legacy_package)
    lg_cache_file = lg_cache_path.joinpath('cache.db')
    for old_file, new_file in zip(
        (lg_config_file, lg_urls_file, lg_hooks_file, lg_cache_file), (config_file, jobs_file, hooks_file, cache_file)
    ):
        if old_file.is_file() and not new_file.is_file():
            new_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old_file, new_file)
            logger.warning(f"Copied {legacy_package} '{old_file}' file to {__project_name__} '{new_file}'.")
            logger.warning(f"You can safely delete '{old_file}'.")


def setup_logger(verbose: Optional[int] = None) -> None:
    """Set up the logger.

    :param verbose: the verbosity level (1 = INFO, 2 = ERROR).
    """
    import platform

    log_level = None
    if verbose is not None:
        if verbose >= 2:
            log_level = 'DEBUG'
        elif verbose == 1:
            log_level = 'INFO'

    logging.basicConfig(format='%(asctime)s %(module)s[%(thread)s] %(levelname)s: %(message)s', level=log_level)
    logger.info(f'{__project_name__}: {__version__} {__copyright__}')
    logger.info(
        f'{platform.python_implementation()}: {platform.python_version()} '
        f'{platform.python_build()} {platform.python_compiler()}'
    )
    logger.info(f'System: {platform.platform()}')


def locate_storage_file(filename: Path, default_path: Path, ext: Optional[str] = None) -> Path:
    """Searches for file both as specified and in the default directory, then retries with 'ext' extension if defined.

    :param filename: The filename.
    :param default_path: The default directory.
    :param ext: The extension, e.g. '.yaml', to add for searching if first scan fails.

    :returns: The filename, either original or one with path where found and/or extension.
    """
    search_filenames = [filename]

    # if ext is given, iterate both on raw filename and the filename with ext if different
    if ext and filename.suffix != ext:
        search_filenames.append(filename.with_suffix(ext))

    for file in search_filenames:
        # return if found
        if file.is_file():
            return file

        # no directory specified (and not in current one): add default one
        if file.parent == PurePath('.'):
            new_file = default_path.joinpath(file)
            if new_file.is_file():
                return new_file

    # no matches found
    return filename


def first_run(command_config: CommandConfig) -> None:
    """Create configuration and jobs files.

    :param command_config: the CommandConfig containing the command line arguments selected.
    """
    if not command_config.config.is_file():
        command_config.config.parent.mkdir(parents=True, exist_ok=True)
        from .storage import YamlConfigStorage

        YamlConfigStorage.write_default_config(command_config.config)
        print(f'Created default config file at {command_config.config}')
        if not command_config.edit_config:
            print(f'> Edit it with {__project_name__} --edit-config')
    if not command_config.jobs.is_file():
        command_config.jobs.parent.mkdir(parents=True, exist_ok=True)
        command_config.jobs.write_text(f'# {__project_name__} jobs file. See {__docs_url__}\n')
        command_config.edit = True
        print(f'Created default jobs file at {command_config.jobs}')
        if not command_config.edit:
            print(f'> Edit it with {__project_name__} --edit')


def handle_unitialized_actions(urlwatch_config: CommandConfig) -> None:
    """Handles CLI actions that do not require all classes etc. to be initialized.  For speed purposes."""

    def _exit(arg: object) -> None:
        logger.info(f'Exiting with exit code {arg}')
        sys.exit(arg)

    def print_new_version() -> int:
        """Will print alert message if a newer version is found on PyPi."""
        print(f'{__project_name__} {__version__}', end='')
        new_release = get_new_version_number(timeout=2)
        if new_release:
            print(
                f'. Release version {new_release} is available; we recommend updating using e.g. '
                f"'pip install -U {__project_name__}'."
            )
            return 0
        elif new_release == '':
            print('. You are running the latest release.')
            return 0
        else:
            print('. Error contacting PyPI to determine the latest release.')
            return 1

    def playwright_install_chrome() -> int:  # pragma: no cover
        """
        Replicates playwright.___main__.main() function, which is called by the playwright executable, in order to
        install the browser executable.

        :return: Playwright's executable return code.
        """
        try:
            from playwright._impl._driver import compute_driver_executable
        except ImportError:
            raise ImportError('Python package playwright is not installed; cannot install the Chrome browser')

        driver_executable = compute_driver_executable()
        env = os.environ.copy()
        env['PW_CLI_TARGET_LANG'] = 'python'
        cmd = [str(driver_executable), 'install', 'chrome']
        logger.info(f"Running playwright CLI: {' '.join(cmd)}")
        completed_process = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if completed_process.returncode:
            print(completed_process.stderr)
            return completed_process.returncode
        if completed_process.stdout:
            logger.info(f'Success! Output of Playwright CLI: {completed_process.stdout}')
        return 0

    if urlwatch_config.check_new:
        _exit(print_new_version())

    if urlwatch_config.install_chrome:  # pragma: no cover
        _exit(playwright_install_chrome())


def main() -> None:  # pragma: no cover
    """The entry point run when __name__ == '__main__'.

    Contains all the high-level logic to instantiate all classes that run the program.

    :raises NotImplementedError: If a `--database-engine` is specified that is not supported.
    :raises RuntimeError: If `--database-engine redis` is selected but `--cache` with a redis URI is not provided.
    """
    # Make sure that PendingDeprecationWarning are displayed from all modules (otherwise only those in __main__ are)
    warnings.filterwarnings('default', category=PendingDeprecationWarning)

    # Issue deprecation warning if running on minimum version supported
    python_version_warning()

    # Path where the config, jobs and hooks files are located
    if sys.platform != 'win32':
        config_path = platformdirs.user_config_path(__project_name__)  # typically ~/.config/{__project_name__}
    else:
        config_path = Path.home().joinpath('Documents').joinpath(__project_name__)

    # Path where the database is located; typically ~/.cache/{__project_name__}
    # or %LOCALAPPDATA%\{__project_name__}\{__project_name__}\Cache
    cache_path = platformdirs.user_cache_path(__project_name__)

    # Default config, jobs, hooks and cache (database) files
    default_config_file = config_path.joinpath('config.yaml')
    default_jobs_file = config_path.joinpath('jobs.yaml')
    default_hooks_file = config_path.joinpath('hooks.py')
    default_cache_file = cache_path.joinpath('cache.db')

    # Check for and if found migrate legacy (urlwatch 2.25) files
    migrate_from_legacy('urlwatch', default_config_file, default_jobs_file, default_hooks_file, default_cache_file)

    # Parse command line arguments
    command_config = CommandConfig(
        sys.argv[1:],
        __project_name__,
        config_path,
        default_config_file,
        default_jobs_file,
        default_hooks_file,
        default_cache_file,
    )

    # Set up the logger to verbose if needed
    setup_logger(command_config.verbose)

    # For speed, run these here
    handle_unitialized_actions(command_config)

    # Only now we can load other modules (so that logging is enabled)
    from .command import UrlwatchCommand
    from .main import Urlwatch
    from .storage import (
        CacheDirStorage,
        CacheRedisStorage,
        CacheSQLite3Storage,
        CacheStorage,
        YamlConfigStorage,
        YamlJobsStorage,
    )

    # Locate config, job and hooks files
    command_config.config = locate_storage_file(command_config.config, command_config.config_path, '.yaml')
    command_config.jobs = locate_storage_file(command_config.jobs, command_config.config_path, '.yaml')
    command_config.hooks = locate_storage_file(command_config.hooks, command_config.config_path, '.py')

    # Check for first run
    if command_config.config == default_config_file and not Path(command_config.config).is_file():
        first_run(command_config)

    # Setup config file API
    config_storage = YamlConfigStorage(command_config.config)  # storage.py

    # Setup database API
    if command_config.database_engine == 'sqlite3':
        cache_storage: CacheStorage = CacheSQLite3Storage(
            command_config.cache, command_config.max_snapshots
        )  # storage.py
    elif any(str(command_config.cache).startswith(prefix) for prefix in ('redis://', 'rediss://')):
        cache_storage = CacheRedisStorage(command_config.cache)  # storage.py
    elif command_config.database_engine == 'redis':
        raise RuntimeError("A redis URI (starting with 'redis://' or 'rediss://' needs to be specified with --cache")
    elif command_config.database_engine == 'textfiles':
        cache_storage = CacheDirStorage(command_config.cache)  # storage.py
    elif command_config.database_engine == 'minidb':
        from .storage_minidb import CacheMiniDBStorage  # legacy code imported only if needed (requires minidb)

        cache_storage = CacheMiniDBStorage(command_config.cache)  # storage.py
    else:
        raise NotImplementedError(f'Database engine {command_config.database_engine} not implemented')

    # Setup jobs file API
    jobs_storage = YamlJobsStorage(command_config.jobs)  # storage.py

    # Setup 'urlwatch'
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    urlwatch_command = UrlwatchCommand(urlwatcher)  # command.py

    # Run 'urlwatch', starting with processing command line arguments
    urlwatch_command.run()


if __name__ == '__main__':
    main()
