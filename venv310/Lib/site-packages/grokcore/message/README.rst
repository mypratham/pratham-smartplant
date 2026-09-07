grokcore.message
*****************

This package provides integration of `z3c.flashmessage`_ for a grok
setup. This means taking care of:

* Registering a global message receiver with the component
  architechture.

* Registering by default a global session-based message source named
  ``session``.

* Optionally (if including ``ram.zcml``) registering a global RAM
  stored message source named ``ram``.

* Providing components to make use of global message receivers and
  sources.

For details about what kind of messages we are talking about here,
please see the `z3c.flashmessage`_ documentation.

.. contents::


Setting up ``grokcore.message``
================================

When being grokked, ``grokcore.message`` registers

* a global session message source named ``session``

* a global message receiver.

Grokking of this package happens when the local ``configure.zcml`` is
executed. In standard Grok-based packages this often happens
automatically.

One can, of course, also grok the package manually:

  >>> import grokcore.component as grok
  >>> grok.testing.grok('grokcore.message')

This setups a global message receiver:

  >>> from z3c.flashmessage.interfaces import IMessageReceiver
  >>> from zope.component import getUtility
  >>> getUtility(IMessageReceiver)
  <z3c.flashmessage.receiver.GlobalMessageReceiver object at 0x...>

It also setups a session-based message source named ``session``:

  >>> from z3c.flashmessage.interfaces import IMessageSource
  >>> getUtility(IMessageSource, name=u'session')
  <z3c.flashmessage.sources.SessionMessageSource object at 0x...>

We provide also a RAM-stored message source that can be enabled by
including ``ram.zcml`` and is not registered by default:

  >>> getUtility(IMessageSource, name=u'ram')
  Traceback (most recent call last):
  ...
  zope.interface.interfaces.ComponentLookupError: (<InterfaceClass z3c.flashmessage.interfaces.IMessageSource>, 'ram')


You can enable this source by including ``ram.zcml`` from
``grokcore.message`` in your ZCML setup like this::

  <configure xmlns="http://namespaces.zope.org/zope">
    <include package="grokcore.message" file="ram.zcml" />
  </configure>

or, of course, by registering a RAMMessageSource manually:

  >>> from zope.component import provideUtility
  >>> from z3c.flashmessage.sources import RAMMessageSource
  >>> ram_source = RAMMessageSource()
  >>> provideUtility(ram_source, name=u'ram')

Now we can get the RAM source:

  >>> getUtility(IMessageSource, name=u'ram')
  <z3c.flashmessage.sources.RAMMessageSource object at 0x...>

Components (API)
================

``grokcore.message`` provides some extra-components and functions
beside the usual components from ``z3c.flashmessage``.

UniqueMessageSource
-------------------

A ``UniqueMessageSource`` is a message source that holds exactly zero
or one message. Note that messages are not stored persistent in a
``UniqueMessageSource`` instance and will be lost after restarting
your Zope instance.

It is a baseclass, which means that you have to derive from it to
register an instance as global utility upon your software being
grokked (see examples below).

Methods:

  **UniqueMessageSource.send(message[, type=u'message'])**
    Send a message ``message`` of type ``type``.

  **UniqueMessageSource.list(type=None)**
    Returns a generator object listing the message if one is stored.

  **UniqueMessageSource.delete(message)**
    Delete the message stored from source, if ``message`` is this
    message.

Convenience functions
---------------------

``grokcore.message`` provides a couple of convenience functions to
feed sources or get data from them.

**grokcore.message.send(message[, type='message'[, name='session']])**

  Send ``message`` to the message source ``name``.

  Returns ``True`` if the message could be sent
  successfully. Otherwise ``False`` is returned:

    >>> import grokcore.message
    >>> grokcore.message.send('Meet at dawn!')
    True

    >>> grokcore.message.send('Meat a fawn!', name='doesnotexist')
    False

**grokcore.message.get_from_source([name=''])**

  Get a list of messages stored at message source registered under
  name ``name`` or ``None``.

  This action never deletes messages from the queried source.

    >>> import grokcore.message
    >>> grokcore.message.get_from_source('session')
    <generator object ...>

    >>> grokcore.message.get_from_source('not-existing') is None
    True

**grokcore.message.receive([name=''])**

  Receive the messages collected by the receiver registered under name
  ``name``.

  >>> import grokcore.message
  >>> msgs = list(grokcore.message.receive())
  >>> msgs
  [<z3c.flashmessage.message.Message object at 0x...>]

  >>> msgs[0].message
  'Meet at dawn!'

  Please note, that this action might delete messages from the sources
  they have been sent to as by 'receiving' messages you indicate that
  the messages have been processed.

  The session source for instance is now empty:

  >>> list(grokcore.message.get_from_source('session'))
  []

  Receiving again will give no results:

  >>> list(grokcore.message.receive())
  []


Examples
========

Creating a ``UniqueMessageSource``:

  >>> from grokcore.message import UniqueMessageSource
  >>> class MyUniqueMessageSource(UniqueMessageSource):
  ...   grok.name('uniq_source')

After being grokked, the source is automatically registered:

  >>> grok.testing.grok_component(
  ...     'MyUniqueMessageSource', MyUniqueMessageSource,
  ...     dotted_name='grokcore.message.tests')
  True

  >>> source = getUtility(IMessageSource, name='uniq_source')
  >>> source
  <...MyUniqueMessageSource object at 0x...>


It provides the methods required by the IMessageSource interface:

  >>> from z3c.flashmessage.interfaces import IMessageSource
  >>> from zope.interface import verify

  >>> verify.verifyClass(IMessageSource, MyUniqueMessageSource)
  True


We can list the message stored in the source:

  >>> source.list()
  <generator object ...>

  >>> list(source.list())
  []

  >>> source.send(message='Hello!', type='message')
  >>> list(source.list())
  [<z3c.flashmessage.message.PersistentMessage object at 0x...>]

  >>> print(list(source.list())[0].message)
  Hello!

When we send another message, the old one will be silenty discarded:

  >>> source.send(message='Hello again!', type='message')
  >>> len(list(source.list()))
  1

  >>> print(list(source.list())[0].message)
  Hello again!

We can delete the message:

  >>> msg = list(source.list())[0]
  >>> source.delete(msg)
  >>> len(list(source.list()))
  0

Examples for the convenience functions can be found above.


.. _z3c.flashmessage: http://pypi.python.org/pypi/z3c.flashmessage
