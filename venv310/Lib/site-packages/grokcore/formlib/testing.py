##############################################################################
#
# Copyright (c) 2007 Zope Foundation and Contributors.
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
"""Grok test helpers
"""
import grokcore.security
import martian
from grokcore.component import Context
from grokcore.component import zcml
from grokcore.security.util import protect_getattr
from grokcore.security.util import protect_setattr
from martian.error import GrokError
from zope.configuration.config import ConfigurationMachine


# Below is a simple grokker + directives that allow you to protect
# attributes of a class with Zope 3 security checkers.  This is needed
# to run the ftests of this package with the standard Zope publication.
# We may hope that something like this eventually makes it into
# grokcore.security.


class Model(Context):
    pass


class protect_get(grokcore.security.require):
    store = martian.MULTIPLE
    default = []

    def validate(self, permission, *attrs):
        super().validate(permission)
        for name in attrs:
            # TODO We should probably check whether 'name' is a valid
            # Python identifier
            martian.validateText(self, name)

    def factory(self, permission, *attrs):
        permission = super().factory(permission)
        return (permission, attrs)

    # Override baseclass's __call__.  This directive can't be used as
    # a decorator at the same time like grok.require() can.
    def __call__(self, *args, **kw):
        raise NotImplementedError


class protect_set(protect_get):
    pass


class ModelSecurityGrokker(martian.ClassGrokker):
    martian.component(Model)
    martian.directive(protect_get)
    martian.directive(protect_set)

    def execute(self, factory, config, protect_get, protect_set, **kw):
        get_names = {}
        for permission, attrs in protect_get:
            for name in attrs:
                if name in get_names:
                    raise GrokError("Duplicate read protection for %r "
                                    "attribute on %r." % (name, factory),
                                    factory)
                get_names[name] = permission

        set_names = {}
        for permission, attrs in protect_set:
            for name in attrs:
                if name in set_names:
                    raise GrokError("Duplicate write protection for %r "
                                    "attribute on %r." % (name, factory),
                                    factory)
                set_names[name] = permission

        for name, permission in get_names.items():
            config.action(
                discriminator=('protectName', factory, name),
                callable=protect_getattr,
                args=(factory, name, permission),
            )
        for name, permission in set_names.items():
            config.action(
                discriminator=('protectSetAttribute', factory, name),
                callable=protect_setattr,
                args=(factory, name, permission),
            )
        return True


def grok(module_name):
    config = ConfigurationMachine()
    zcml.do_grok('grokcore.component.meta', config)
    zcml.do_grok('grokcore.security.meta', config)
    zcml.do_grok('grokcore.view.meta', config)
    zcml.do_grok('grokcore.formlib.meta', config)
    zcml.do_grok(module_name, config)
    config.execute_actions()
