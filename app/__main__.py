"""Project entry point. Module CLIs own their commands; DB upgrade is shared."""
import sys
from app.shared.db.migrations import upgrade_database


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ['db', 'upgrade']:
        upgrade_database()
        return 0
    if args and args[0] == 'news':
        from app.modules.news.cli import main as news_main
        return news_main(args[1:])
    if args and args[0] == 'companies':
        from app.modules.companies.cli import main as companies_main
        return companies_main(args[1:])
    print('Usage: python -m app db upgrade | python -m app news --help | python -m app companies --help')
    return 0 if not args or args == ['--help'] else 2


if __name__ == '__main__':
    sys.exit(main())
