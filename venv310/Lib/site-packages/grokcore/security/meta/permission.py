#############################################################################
#
# Copyright (c) 2006-2007 Zope Foundation and Contributors.
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
"""Grokkers for security-related components."""

import grokcore.component
import martian
from martian.error import GrokError
from zope.security.interfaces import IPermission

import grokcore.security


def default_fallback_to_name(factory, module, name, **data):
    return name


class PermissionGrokker(martian.ClassGrokker):
    martian.component(grokcore.security.Permission)
    martian.priority(1500)
    martian.directive(grokcore.component.name)
    martian.directive(grokcore.component.title,
                      get_default=default_fallback_to_name)
    martian.directive(grokcore.component.description)

    def execute(self, factory, config, name, title, description, **kw):
        if not name:
            raise GrokError(
                "A permission needs to have a dotted name for its id. Use "
                "grok.name to specify one.", factory)
        permission = factory(str(name), str(title), str(description))

        config.action(
            discriminator=('utility', IPermission, name),
            callable=grokcore.component.provideUtility,
            args=(permission, IPermission, name),
            order=-1  # need to do this early in the process
        )
        return True
