##############################################################################
#
# Copyright (c) 2006-2009 Zope Foundation and Contributors.
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
"""Chameleon page template components"""

import os
import sys
import typing

import chameleon.i18n
import martian
import zope.i18n
from chameleon.tales import ExistsExpr
from chameleon.tales import ImportExpr
from chameleon.tales import NotExpr
from chameleon.tales import PythonExpr
from chameleon.tales import StringExpr
from chameleon.tales import StructureExpr
from chameleon.zpt.template import PageTemplate
from chameleon.zpt.template import PageTemplateFile
from grokcore.component import GlobalUtility
from grokcore.component import implementer
from grokcore.component import name
from grokcore.view import interfaces
from grokcore.view.components import GrokTemplate
from z3c.pt.expressions import PathExpr
from z3c.pt.expressions import ProviderExpr


class PageTemplate(PageTemplate):
    """A Chameleon page template suitable for use with views.

    It defines the path and provider expression types to the template in
    addition to the "standard" expressions types.
    """
    expression_types = {
        'python': PythonExpr,
        'string': StringExpr,
        'not': NotExpr,
        'path': PathExpr,
        'provider': ProviderExpr,
        'exists': ExistsExpr,
        'import': ImportExpr,
        'structure': StructureExpr,
    }

    def render(self, **vars):
        # zope.i18n.translate will call negociate to retrieve the
        # target_language if it is None.
        request = vars.get('request')
        if 'target_language' not in vars:
            vars['target_language'] = zope.i18n.negotiate(request)

        if vars.get('target_language') is not None:

            def translate(
                    msgid, domain=None, mapping=None, context=None,
                    target_language=None, default=None):
                # We swap context with the request, that is required for
                # zope.i18n.translate.
                if isinstance(msgid, typing.Hashable):
                    return zope.i18n.translate(
                        msgid, domain, mapping, request, target_language,
                        default)
                return msgid

            vars['translate'] = translate
        else:
            vars['translate'] = chameleon.i18n.simple_translate

        return super().render(**vars)


def _module_relative_to_abs(ctx, filename):
    # Taken and adapted from z3c.pth.pagetemplate.
    if os.path.isabs(filename):
        return filename
    for depth in (2, 3):
        frame = sys._getframe(depth)
        package_name = frame.f_globals.get('__name__', None)
        if package_name is not None and package_name != ctx:
            module = sys.modules[package_name]
            try:
                path = module.__path__[0]
            except AttributeError:
                path = module.__file__
                path = path[:path.rfind(os.sep)]
            break
        else:
            package_path = frame.f_globals.get('__file__', None)
            if package_path is not None:
                path = os.path.dirname(package_path)
                break
    return os.path.join(path, filename)


class PageTemplateFile(PageTemplate, PageTemplateFile):
    """A Chameleon page template file suitable for use with views.

    Takes an absolute path to the template file as the first argument.
    """

    def __init__(self, filename):
        filename = _module_relative_to_abs(self, filename)
        super().__init__(filename)


class ChameleonPageTemplate(GrokTemplate):
    """Encapsulates a Chameleon-based template as a GrokTemplate
    implementation.

    Used for Grok View components by way of the grok.template() directive.
    """

    def setFromString(self, string):
        self._filename = None
        self._template = PageTemplate(string)

    def setFromFilename(self, filename, _prefix=None):
        self._filename = filename
        self._prefix = _prefix
        self._template = PageTemplateFile(os.path.join(_prefix, filename))
        return

    @property
    def macros(self):
        return self._template.macros

    def render(self, view):
        context = self.getNamespace(view)
        return self._template(**context)


class ChameleonPageTemplateFile(ChameleonPageTemplate):
    """Encapsulates a Chameleon-based template file as a GrokTemplate
    implementation.

    Used for Grok View components by way of the grok.template() directive.

    The filename will be relative to the module in which the Grok View
    component is defined.
    """

    def __init__(self, filename, _prefix=None):
        self.__grok_module__ = martian.util.caller_module()
        if _prefix is None:
            module = sys.modules[self.__grok_module__]
            _prefix = os.path.dirname(module.__file__)
        self.setFromFilename(filename, _prefix)


@implementer(interfaces.ITemplateFileFactory)
class ChameleonPageTemplateFactory(GlobalUtility):
    name('cpt')

    def __call__(self, filename, _prefix=None):
        return ChameleonPageTemplate(filename=filename, _prefix=_prefix)
