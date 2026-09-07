"""
  >>> from grokcore.content import Container, OrderedContainer
  >>> from grokcore.content import IContainer, IOrderedContainer
  >>> from zope.interface.verify import verifyClass

A grokcore.content.Container verifies the interface IContainer::

  >>> class Cave(Container):
  ...   pass

  >>> verifyClass(IContainer, Cave)
  True

It also implements the IContext interface, allowing it to be taken as the
default context of a grok module::

  >>> from grokcore.component.interfaces import IContext
  >>> IContext.implementedBy(Cave)
  True

A grokcore.content.OrderedContainer verifies both the interface IContainer
and IOrderedContainer::

  >>> class CleanCave(OrderedContainer):
  ...   pass

  >>> verifyClass(IContainer, CleanCave)
  True

  >>> verifyClass(IOrderedContainer, CleanCave)
  True

Like the grokcore.content.Container, the OrderedContainer is an IContext::

  >>> IContext.implementedBy(CleanCave)
  True

"""


def test_suite():
    import doctest
    suite = doctest.DocTestSuite(
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS)
    return suite
