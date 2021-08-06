"""Test commands."""
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path, PurePath

import pytest

from webchanges import __copyright__, __min_python_version__, __project_name__, __version__
from webchanges.cli import (
    first_run,
    locate_storage_file,
    migrate_from_legacy,
    python_version_warning,
    setup_logger_verbose,
)
from webchanges.command import UrlwatchCommand
from webchanges.config import CommandConfig
from webchanges.main import Urlwatch
from webchanges.storage import CacheSQLite3Storage, YamlConfigStorage, YamlJobsStorage

here = Path(__file__).parent

config_path = here.joinpath('data')
tmp_path = Path(tempfile.mkdtemp())
base_config_file = config_path.joinpath('config.yaml')
config_file = tmp_path.joinpath('config.yaml')
shutil.copyfile(base_config_file, config_file)
base_jobs_file = config_path.joinpath('jobs-echo_test.yaml')
jobs_file = tmp_path.joinpath('jobs-echo_test.yaml')
shutil.copyfile(base_jobs_file, jobs_file)
cache_file = ':memory:'
base_hooks_file = config_path.joinpath('hooks_test.py')
hooks_file = tmp_path.joinpath('hooks_test.py')
shutil.copyfile(base_hooks_file, hooks_file)

config_storage = YamlConfigStorage(config_file)
config_storage.load()
cache_storage = CacheSQLite3Storage(cache_file)
jobs_storage = YamlJobsStorage(jobs_file)
command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, True)
urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py

editor = os.getenv('EDITOR')
if os.name == 'nt':
    os.environ['EDITOR'] = 'rundll32'
else:
    os.environ['EDITOR'] = 'true'
visual = os.getenv('VISUAL')
if visual:
    del os.environ['VISUAL']


@pytest.fixture(scope='module', autouse=True)
def cleanup(request):
    """Cleanup once we are finished."""

    def finalizer():
        """Cleanup once we are finished."""
        if editor:
            os.environ['EDITOR'] = editor
        if visual:
            os.environ['VISUAL'] = visual
        try:
            urlwatcher.close()
        except AttributeError:
            pass
        # Python 3.9: config_edit = config_file.with_stem(config_file.stem + '_edit')
        # Python 3.9: hooks_edit = hooks_file.with_stem(hooks_file.stem + '_edit')
        config_edit = config_file.joinpath(config_file.stem + '_edit' + ''.join(config_file.suffixes))
        hooks_edit = hooks_file.joinpath(hooks_file.stem + '_edit' + ''.join(hooks_file.suffixes))
        for filename in (config_edit, hooks_edit):
            # Python 3.8: replace with filename.unlink(missing_ok=True)
            if filename.is_file():
                filename.unlink()

    request.addfinalizer(finalizer)


def test_python_version_warning(capsys):
    """Test issuance of deprecation warning message when running on minimum version supported."""
    python_version_warning()
    message = capsys.readouterr().out
    if sys.version_info[0:2] == __min_python_version__:
        current_minor_version = '.'.join(str(n) for n in sys.version_info[0:2])
        assert message.startswith(
            f'WARNING: Support for Python {current_minor_version} will be ending three years from the date Python '
        )
    else:
        assert not message


def test_migration():
    """Test check for existence of legacy urlwatch 2.2 files in urlwatch dir."""
    assert migrate_from_legacy('urlwatch', config_file, jobs_file, hooks_file, Path(cache_file)) is None


def test_first_run(capsys, tmp_path):
    """Test creation of default config and jobs files at first run."""
    config_file2 = tmp_path.joinpath('config.yaml')
    jobs_file2 = tmp_path.joinpath('jobs.yaml')
    command_config2 = CommandConfig(__project_name__, tmp_path, config_file2, jobs_file2, hooks_file, cache_file, True)
    assert first_run(command_config2) is None
    message = capsys.readouterr().out
    assert 'Created default config file at ' in message
    assert 'Created default jobs file at ' in message


def test_edit_hooks(capsys):
    setattr(command_config, 'edit_hooks', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'edit_hooks', False)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert message == f'Saved edits in {urlwatch_command.urlwatch_config.hooks}\n'


def test_edit_hooks_fail(capsys):
    editor = os.getenv('EDITOR')
    os.environ['EDITOR'] = 'does_not_exist_and_should_trigger_an_error'
    setattr(command_config, 'edit_hooks', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(OSError) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'edit_hooks', False)
    os.environ['EDITOR'] = editor
    hooks_edit = urlwatch_command.urlwatch_config.hooks.parent.joinpath(
        urlwatch_command.urlwatch_config.hooks.stem + '_edit' + ''.join(urlwatch_command.urlwatch_config.hooks.suffixes)
    )
    hooks_edit.unlink()
    assert pytest_wrapped_e.value.args[0] == (
        'pytest: reading from stdin while output is captured!  Consider using `-s`.'
    )
    message = capsys.readouterr().out
    assert 'Parsing failed:' in message


def test_show_features_and_verbose(capsys):
    setattr(command_config, 'features', True)
    setattr(command_config, 'verbose', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'features', False)
    setattr(command_config, 'verbose', False)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert '* browser - Retrieve a URL, emulating a real web browser (use_browser: true).' in message


def test_list_jobs_verbose(capsys):
    setattr(command_config, 'list', True)
    urlwatch_config_verbose = urlwatcher.urlwatch_config.verbose
    urlwatcher.urlwatch_config.verbose = False
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'list', False)
    urlwatcher.urlwatch_config.verbose = urlwatch_config_verbose
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert message == '  1: Sample webchanges job; used by command_test.py (echo test)\n'


def test_list_jobs_not_verbose(capsys):
    setattr(command_config, 'list', True)
    urlwatch_config_verbose = urlwatcher.urlwatch_config.verbose
    urlwatcher.urlwatch_config.verbose = False
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'list', False)
    urlwatcher.urlwatch_config.verbose = urlwatch_config_verbose
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert message == '  1: Sample webchanges job; used by command_test.py (echo test)\n'


def test__find_job():
    urlwatch_command = UrlwatchCommand(urlwatcher)
    assert urlwatch_command._find_job('https://example.com/') is None


def test__find_job_index_error():
    urlwatch_command = UrlwatchCommand(urlwatcher)
    assert urlwatch_command._find_job(100) is None


def test__get_job():
    urlwatch_command = UrlwatchCommand(urlwatcher)
    assert urlwatch_command._get_job(1).get_location() == 'echo test'


def test__get_job_index_error(capsys):
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command._get_job(100).get_location()
    assert pytest_wrapped_e.value.code == 1
    message = capsys.readouterr().out
    assert message == 'Job not found: 100\n'


def test_test_job(capsys):
    setattr(command_config, 'test_job', 1)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'test_job', None)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    message = message.replace('\n\n ', '\n').replace('\r', '')  # Python 3.6
    assert message == (
        '\n'
        'Sample webchanges job; used by command_test.py\n'
        '----------------------------------------------\n'
        '\n'
        'test\n'
        '\n'
    )


def test_test_diff_and_joblist(capsys):
    try:
        jobs_file = config_path.joinpath('jobs-time.yaml')
        jobs_storage = YamlJobsStorage(jobs_file)
        command_config = CommandConfig(
            __project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False
        )
        urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
        if os.name == 'nt':
            urlwatcher.jobs[0].command = 'echo %time% %random%'

        setattr(command_config, 'test_diff', 1)
        urlwatch_command = UrlwatchCommand(urlwatcher)
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            urlwatch_command.handle_actions()
        setattr(command_config, 'test_diff', None)
        assert pytest_wrapped_e.value.code == 1
        message = capsys.readouterr().out
        assert message == 'Not enough historic data available (need at least 2 different snapshots)\n'

        # run once
        # also testing joblist
        urlwatcher.urlwatch_config.joblist = [1]
        urlwatcher.run_jobs()
        cache_storage._copy_temp_to_permanent(delete=True)
        urlwatcher.urlwatch_config.joblist = None

        # test invalid joblist
        urlwatcher.urlwatch_config.joblist = [999]
        with pytest.raises(IndexError) as pytest_wrapped_e:
            urlwatcher.run_jobs()
        assert pytest_wrapped_e.value.args[0] == 'Job index 999 out of range (found 1 jobs)'
        urlwatcher.urlwatch_config.joblist = None

        # run twice
        time.sleep(0.0001)
        urlwatcher.run_jobs()
        cache_storage._copy_temp_to_permanent(delete=True)
        guid = urlwatcher.jobs[0].get_guid()
        history = cache_storage.get_history_data(guid)
        assert len(history) == 2

        # test diff (unified) with diff_filter, tz, and contextlines
        setattr(command_config, 'test_diff', 1)
        urlwatcher.jobs[0].diff_filter = {'strip': ''}
        urlwatcher.jobs[0].tz = 'Etc/UTC'
        urlwatcher.jobs[0].contextlines = 2
        urlwatch_command = UrlwatchCommand(urlwatcher)
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            urlwatch_command.handle_actions()
        setattr(command_config, 'test_diff', None)
        assert pytest_wrapped_e.value.code == 0
        message = capsys.readouterr().out
        assert '=== Filtered diff between state 0 and state -1 ===\n' in message
        # rerun to reuse cached _generated_diff
        setattr(command_config, 'test_diff', 1)
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            urlwatch_command.handle_actions()
        setattr(command_config, 'test_diff', None)
        message = capsys.readouterr().out
        assert '=== Filtered diff between state 0 and state -1 ===\n' in message

        # test diff (using outside differ)
        setattr(command_config, 'test_diff', 1)
        # Diff tools return 0 for "nothing changed" or 1 for "files differ", anything else is an error
        if os.name == 'nt':
            urlwatcher.jobs[0].diff_tool = 'cmd /C exit 1 & rem '
        else:
            urlwatcher.jobs[0].diff_tool = 'bash -c exit 1 # '
        urlwatch_command = UrlwatchCommand(urlwatcher)
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            urlwatch_command.handle_actions()
        setattr(command_config, 'test_diff', None)
        assert pytest_wrapped_e.value.code == 0
        message = capsys.readouterr().out
        assert '=== Filtered diff between state 0 and state -1 ===\n' in message
    finally:
        urlwatcher.cache_storage.delete(guid)


def test_list_error_jobs(capsys):
    setattr(command_config, 'errors', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'errors', False)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert 'Jobs, if any, with errors or returning no data after filtering.\n' in message


def test_modify_urls(capsys):
    """Test --add JOB and --delete JOB."""
    # save current contents of job file
    before_file = jobs_file.read_text()

    # add new job
    setattr(command_config, 'add', 'url=https://www.example.com/#test_modify_urls')
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'add', None)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert "Adding <url url='https://www.example.com/#test_modify_urls'" in message

    # delete the job just added
    setattr(command_config, 'delete', 'https://www.example.com/#test_modify_urls')
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'delete', None)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert "Removed <url url='https://www.example.com/#test_modify_urls'" in message

    # check that the job file is identical to before the add/delete operations
    after_file = jobs_file.read_text()
    assert after_file == before_file


def test_delete_snapshot(capsys):
    jobs_file = config_path.joinpath('jobs-time.yaml')
    jobs_storage = YamlJobsStorage(jobs_file)
    command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False)
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    if os.name == 'nt':
        urlwatcher.jobs[0].command = 'echo %time% %random%'

    setattr(command_config, 'delete_snapshot', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'delete_snapshot', False)
    message = capsys.readouterr().out
    assert message[:43] == 'No snapshots found to be deleted for Job 1:'
    assert pytest_wrapped_e.value.code == 1

    # run once
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    guid = urlwatcher.jobs[0].get_guid()
    history = cache_storage.get_history_data(guid)
    assert len(history) == 1

    # run twice
    time.sleep(0.0001)
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    history = cache_storage.get_history_data(guid)
    assert len(history) == 2

    # delete once
    setattr(command_config, 'delete_snapshot', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'delete_snapshot', False)
    message = capsys.readouterr().out
    assert message[:31] == 'Deleted last snapshot of Job 1:'
    assert pytest_wrapped_e.value.code == 0

    # delete twice
    setattr(command_config, 'delete_snapshot', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'delete_snapshot', False)
    message = capsys.readouterr().out
    assert message[:31] == 'Deleted last snapshot of Job 1:'
    assert pytest_wrapped_e.value.code == 0

    # test all empty
    setattr(command_config, 'delete_snapshot', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'delete_snapshot', False)
    message = capsys.readouterr().out
    assert message[:43] == 'No snapshots found to be deleted for Job 1:'
    assert pytest_wrapped_e.value.code == 1


def test_gc_cache(capsys):
    jobs_file = config_path.joinpath('jobs-time.yaml')
    jobs_storage = YamlJobsStorage(jobs_file)
    command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False)
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    if os.name == 'nt':
        urlwatcher.jobs[0].command = 'echo %time% %random%'
    guid = urlwatcher.jobs[0].get_guid()

    # run once to save the job from 'jobs-time.yaml'
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    history = cache_storage.get_history_data(guid)
    assert len(history) == 1

    # set job file to a different one
    jobs_file = config_path.joinpath('jobs-echo_test.yaml')
    command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False)
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    urlwatch_command = UrlwatchCommand(urlwatcher)

    # run gc_cache and check that it deletes the snapshot of the job no longer being tracked
    setattr(command_config, 'gc_cache', True)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'gc_cache', False)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    if os.name == 'nt':
        assert message == f'Deleting: {guid} (no longer being tracked)\n'
    else:
        # TODO: for some reason, Linux message is ''.  Need to figure out why.
        ...


def test_clean_cache(capsys):
    setattr(command_config, 'clean_cache', True)
    urlwatcher.cache_storage = CacheSQLite3Storage(cache_file)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'clean_cache', False)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert message == ''


def test_rollback_cache(capsys):
    setattr(command_config, 'rollback_cache', True)
    urlwatcher.cache_storage = CacheSQLite3Storage(cache_file)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.handle_actions()
    setattr(command_config, 'rollback_cache', False)
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert 'No snapshots found after' in message


def test_check_edit_config():
    setattr(command_config, 'edit_config', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_edit_config()
    setattr(command_config, 'edit_config', False)
    assert pytest_wrapped_e.value.code == 0


def test_check_edit_config_fail(capsys):
    editor = os.getenv('EDITOR')
    os.environ['EDITOR'] = 'does_not_exist_and_should_trigger_an_error'
    setattr(command_config, 'edit_config', True)
    urlwatch_command = UrlwatchCommand(urlwatcher)
    with pytest.raises(OSError):
        urlwatch_command.check_edit_config()
    setattr(command_config, 'edit_config', False)
    os.environ['EDITOR'] = editor
    filename = urlwatcher.config_storage.filename
    file_edit = filename.parent.joinpath(filename.stem + '_edit' + ''.join(filename.suffixes))
    file_edit.unlink()
    message = capsys.readouterr().out
    assert 'Errors in file:' in message


def test_check_telegram_chats(capsys):
    urlwatch_command = UrlwatchCommand(urlwatcher)
    setattr(command_config, 'telegram_chats', False)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_telegram_chats()
    assert pytest_wrapped_e.value.code == 1
    message = capsys.readouterr().out
    assert message == 'You need to set up your bot token first (see documentation)\n'

    setattr(command_config, 'telegram_chats', True)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_telegram_chats()
    assert pytest_wrapped_e.value.code == 1
    message = capsys.readouterr().out
    assert message == 'You need to set up your bot token first (see documentation)\n'

    urlwatch_command.urlwatcher.config_storage.config['report']['telegram']['bot_token'] = 'bogus'  # nosec
    setattr(command_config, 'telegram_chats', True)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_telegram_chats()
    assert pytest_wrapped_e.value.code == 1
    message = capsys.readouterr().out
    assert message == 'Error with token bogus: Not Found\n'

    if os.getenv('TELEGRAM_TOKEN'):
        urlwatch_command.urlwatcher.config_storage.config['report']['telegram']['bot_token'] = os.getenv(
            'TELEGRAM_TOKEN'
        )
        setattr(command_config, 'telegram_chats', True)
        with pytest.raises(SystemExit):
            urlwatch_command.check_telegram_chats()
        message = capsys.readouterr().out
        assert 'Say hello to your bot at https://t.me/' in message
    else:
        print('Cannot fully test Telegram as no TELEGRAM_TOKEN environment variable found')


def test_check_test_reporter(capsys):
    urlwatch_command = UrlwatchCommand(urlwatcher)
    setattr(command_config, 'test_reporter', 'stdout')
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_test_reporter()
    assert pytest_wrapped_e.value.code == 0
    message = capsys.readouterr().out
    assert '01. NEW: Newly Added\n' in message

    urlwatch_command.urlwatcher.config_storage.config['report']['stdout']['enabled'] = False
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_test_reporter()
    assert pytest_wrapped_e.value.code == 1
    message = capsys.readouterr().out
    assert 'Reporter is not enabled/configured: stdout\n' in message

    setattr(command_config, 'test_reporter', 'does_not_exist')
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_test_reporter()
    assert pytest_wrapped_e.value.code == 1
    message = capsys.readouterr().out
    assert 'No such reporter: does_not_exist\n' in message


def test_check_smtp_login():
    urlwatch_command = UrlwatchCommand(urlwatcher)
    setattr(command_config, 'smtp_login', False)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_smtp_login()
    assert pytest_wrapped_e.value.code == 1
    setattr(command_config, 'smtp_login', True)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_smtp_login()
    assert pytest_wrapped_e.value.code == 1


def test_check_xmpp_login():
    urlwatch_command = UrlwatchCommand(urlwatcher)
    setattr(command_config, 'xmpp_login', False)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_xmpp_login()
    assert pytest_wrapped_e.value.code == 1
    setattr(command_config, 'xmpp_login', True)
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        urlwatch_command.check_xmpp_login()
    assert pytest_wrapped_e.value.code == 1


def test_setup_logger_verbose(caplog):
    caplog.set_level(logging.DEBUG)
    setup_logger_verbose()
    assert f' {__project_name__}: {__version__} {__copyright__}\n' in caplog.text


def test_locate_storage_file():
    file = locate_storage_file(Path('test'), Path('nowhere'), '.noext')
    assert file == PurePath('test')


def test_job_states_verb():
    jobs_file = config_path.joinpath('jobs-time.yaml')
    jobs_storage = YamlJobsStorage(jobs_file)
    cache_storage = CacheSQLite3Storage(cache_file)
    command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False)
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    urlwatcher.jobs[0].command = 'echo TEST'

    # run once
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[0].verb == 'new'

    # run twice
    urlwatcher.run_jobs()
    assert urlwatcher.report.job_states[1].verb == 'unchanged'


def test_job_states_verb_notimestamp_unchanged():
    jobs_file = config_path.joinpath('jobs-time.yaml')
    jobs_storage = YamlJobsStorage(jobs_file)
    cache_storage = CacheSQLite3Storage(cache_file)
    command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False)
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    urlwatcher.jobs[0].command = 'echo TEST'

    # run once
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[0].verb == 'new'

    # modify database
    guid = urlwatcher.cache_storage.get_guids()[0]
    data, timestamp, tries, etag = urlwatcher.cache_storage.load(guid)
    urlwatcher.cache_storage.delete(guid)
    urlwatcher.cache_storage.save(guid=guid, data=data, timestamp=0, tries=1, etag=etag)
    cache_storage._copy_temp_to_permanent(delete=True)

    # run twice
    urlwatcher.run_jobs()
    assert urlwatcher.report.job_states[1].verb == 'unchanged'


def test_job_states_verb_notimestamp_changed():
    jobs_file = config_path.joinpath('jobs-time.yaml')
    jobs_storage = YamlJobsStorage(jobs_file)
    cache_storage = CacheSQLite3Storage(cache_file)
    command_config = CommandConfig(__project_name__, config_path, config_file, jobs_file, hooks_file, cache_file, False)
    urlwatcher = Urlwatch(command_config, config_storage, cache_storage, jobs_storage)  # main.py
    urlwatcher.jobs[0].command = 'echo TEST'

    # run once
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[-1].verb == 'new'

    # modify database (save no timestamp)
    guid = urlwatcher.jobs[0].get_guid()
    data, timestamp, tries, etag = urlwatcher.cache_storage.load(guid)
    urlwatcher.cache_storage.delete(guid)
    urlwatcher.cache_storage.save(guid=guid, data=data, timestamp=0, tries=tries, etag=etag)
    cache_storage._copy_temp_to_permanent(delete=True)

    # run twice
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[-1].verb == 'unchanged'

    # modify database to 1 try
    data, timestamp, tries, etag = urlwatcher.cache_storage.load(guid)
    urlwatcher.cache_storage.delete(guid)
    urlwatcher.cache_storage.save(guid=guid, data=data, timestamp=timestamp, tries=1, etag=etag)
    cache_storage._copy_temp_to_permanent(delete=True)
    # run again
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[-1].verb == 'unchanged'

    # modify database to no timestamp
    urlwatcher.cache_storage.delete(guid)
    urlwatcher.cache_storage.save(guid=guid, data=data, timestamp=0, tries=tries, etag=etag)
    cache_storage._copy_temp_to_permanent(delete=True)
    # run again
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[-1].verb == 'unchanged'

    # modify database to no timestamp and 1 try
    urlwatcher.cache_storage.delete(guid)
    urlwatcher.cache_storage.save(guid=guid, data=data, timestamp=0, tries=1, etag=etag)
    cache_storage._copy_temp_to_permanent(delete=True)
    # run again
    urlwatcher.run_jobs()
    cache_storage._copy_temp_to_permanent(delete=True)
    assert urlwatcher.report.job_states[-1].verb == 'unchanged'
