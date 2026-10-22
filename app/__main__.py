"""Project entry point. Module CLIs own their commands; DB upgrade is shared."""
import sys
from app.shared.db.migrations import upgrade_database


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ['db', 'upgrade']:
        upgrade_database()
        return 0
    modules = {'news': 'app.modules.news.cli', 'companies': 'app.modules.companies.cli',
               'analytics': 'app.modules.analytics.cli'}
    if args and args[0] in modules:
        from importlib import import_module
        return import_module(modules[args[0]]).main(args[1:])
    print('Usage: python -m app db upgrade | python -m app news --help | python -m app companies --help | python -m app analytics --help')
    return 0 if not args or args == ['--help'] else 2


if __name__ == '__main__': sys.exit(main())
