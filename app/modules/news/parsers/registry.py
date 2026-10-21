from .kommersant import KommersantParser
from .vedomosti import VedomostiParser
from .interfax import InterfaxParser

SOURCES = {
    'kommersant': KommersantParser(),
    'vedomosti': VedomostiParser(),
    'interfax': InterfaxParser(),
}
