##############################################################################
#
# Copyright (c) 2001, 2002 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""A registry for Request-Publication factories.
"""
from zope.configuration.exceptions import ConfigurationError
from zope.interface import implementer

from zope.app.publication.interfaces import IRequestPublicationRegistry


@implementer(IRequestPublicationRegistry)
class RequestPublicationRegistry:
    """The registry implements a three stage lookup for registered factories
    that have to deal with requests::

      {method > { mimetype -> [{'priority' : some_int,
                                 'factory' :  factory,
                                 'name' : some_name }, ...
                                ]
                  },
      }

    The `priority` is used to define a lookup-order when multiple factories
    are registered for the same method and mime-type.
    """

    def __init__(self):
        self._d = {}   # method -> { mimetype -> {factories_data}}

    def register(self, method, mimetype, name, priority, factory):
        """Register a factory for method+mimetype"""
        # initialize the two-level deep nested datastructure if necessary
        if method not in self._d:
            self._d[method] = {}
        if mimetype not in self._d[method]:
            self._d[method][mimetype] = []
        factories_data = self._d[method][mimetype]

        # Check if there is already a registered publisher factory (check by
        # name).  If yes then it will be removed and replaced by a new
        # publisher.
        for pos, d in enumerate(factories_data):
            if d['name'] == name:
                del factories_data[pos]
                break
        # add the publisher factory + additional informations
        factories_data.append(
            {'name': name, 'factory': factory, 'priority': priority})

        # order by descending priority
        factories_data.sort(key=lambda v: v['priority'], reverse=True)

        # check if the priorities are unique
        priorities = [item['priority'] for item in factories_data]
        if len(set(priorities)) != len(factories_data):
            raise ConfigurationError('All registered publishers for a given '
                                     'method+mimetype must have distinct '
                                     'priorities. Please check your ZCML '
                                     'configuration')

    def getFactoriesFor(self, method, mimetype):
        if ';' in mimetype:
            # `mimetype` might be something like 'text/xml; charset=utf8'. In
            # this case we are only interested in the first part.
            mimetype = mimetype.split(';')[0]

        try:
            return self._d[method][mimetype.strip()]
        except KeyError:
            return None

    def lookup(self, method, mimetype, environment):
        """Lookup a factory for a given method+mimetype and a environment.
        """
        for m, mt in ((method, mimetype), (method, '*'), ('*', '*')):
            # Collect, in order, from most specific to most generic, the
            # factories that potentially handle the given environment.
            # Now iterate over all factory candidates and let them
            # introspect the request environment to figure out if
            # they can handle the request. The first one to accept the
            # environment, wins.
            found = self.getFactoriesFor(m, mt)
            if found is None:
                continue
            for info in found:
                factory = info['factory']
                if factory.canHandle(environment):
                    return factory
        raise ConfigurationError(
            f'No registered publisher found for ({method}/{mimetype})')


factoryRegistry = RequestPublicationRegistry()

try:
    import zope.testing.cleanup
except ModuleNotFoundError:
    pass
else:
    zope.testing.cleanup.addCleanUp(lambda: factoryRegistry.__init__())
