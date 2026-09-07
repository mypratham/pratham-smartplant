"""

The grokcore.content.Container is a a model that is also a container.
It has a dictionary API. It in fact stores its information in a BTree so
you can store a lot of items in a scalable way.

    >>> from zope.container.interfaces import IContainer
    >>> bag = BoneBag()
    >>> IContainer.providedBy(bag)
    True

    >>> from zope.container.btree import BTreeContainer
    >>> isinstance(bag, BTreeContainer)
    True

We had problems when switching to grokcore.content.Container
with the __parent__ attribute being set, we better make sure
this doesn't happen again:

    >>> skull = Bone()
    >>> print(skull.__parent__)
    None
    >>> print(skull.__name__)
    None
    >>> bag['skull'] = skull
    >>> skull.__parent__
    <grokcore.content.tests.test_container.BoneBag object at 0x...>

Note how we prefix the print output in order to have the ellipsis work as
the output for the __name__ is slightly different between python 2 and
python 3.

    >>> 'skull name';skull.__name__
    'skull name'...'skull'

"""

from grokcore.content import Container
from grokcore.content import Model


class BoneBag(Container):
    pass


class Bone(Model):
    pass


def test_suite():
    import doctest
    suite = doctest.DocTestSuite(
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS)
    return suite
