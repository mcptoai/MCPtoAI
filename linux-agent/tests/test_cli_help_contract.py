"""Ensure public CLI commands remain discoverable, including nested actions."""
from mcptoai_linux.cli import build_parser
import argparse


def test_every_command_is_visible_and_documented():
    parser = build_parser()
    root_help = parser.format_help()
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    for name, child in commands.choices.items():
        assert name in root_help
        assert child.description, f'{name} missing description'
        assert child.format_help(), name
        assert child.get_default('fn') is not None, f'{name} missing handler'
        for action in child._actions:
            if isinstance(action, argparse._SubParsersAction):
                for subname, nested in action.choices.items():
                    assert subname in child.format_help(), f'{name} {subname} not discoverable'
                    assert nested.format_help(), f'{name} {subname} missing help'


def test_new_features_and_docker_migration_are_discoverable():
    parser = build_parser()
    help_text = parser.format_help()
    for term in ('activity-list', 'activity-clear', 'activity-recording',
                 'history', 'jobs', 'shell', 'mcp', 'update', '/data',
                 '/home/mcptoai/.config', 'docker logs', 'rollback'):
        assert term.lower() in help_text.lower(), term
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    for name in ('activity-list', 'activity-clear', 'activity-recording'):
        assert 'Example' in commands.choices[name].format_help()


def test_command_surface_matches_pre_pr_main():
    """Historical baseline is captured from main before PR-G help changes."""
    import json
    baseline = json.loads((__import__('pathlib').Path(__file__).parent / 'fixtures' / 'cli_commands_main.json').read_text())
    parser = build_parser()
    root = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(root.choices) >= set(baseline['commands'])
    for name, actions in baseline['nested'].items():
        child = root.choices[name]
        nested = next(a for a in child._actions if isinstance(a, argparse._SubParsersAction))
        assert set(nested.choices) >= set(actions), name


def test_server_only_commands_are_not_silently_claimed_as_preserved():
    """Prevent declaring deployed-only commands supported without implementation."""
    import argparse
    parser = build_parser()
    root = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    # The provided server help lists these, but neither exists in historical
    # source tags or main. Track the discrepancy explicitly until source is found.
    for name in ('attachments', 'stop'):
        if name in root.choices:
            assert root.choices[name].get_default('fn') is not None


def test_stop_alias_routes_to_service_stop(monkeypatch):
    from mcptoai_linux import cli
    called = []
    monkeypatch.setattr(cli, 'cmd_service', lambda args: called.append(args.action))
    cli.build_parser().parse_args(['stop']).fn(None)
    assert called == ['stop']
