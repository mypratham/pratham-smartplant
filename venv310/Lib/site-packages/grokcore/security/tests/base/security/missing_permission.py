"""
A permission has to be defined first (using grok.Permission for example)
before it can be used in grok.require().

>>> grok.testing.grok(__name__)
Traceback (most recent call last):
...
zope.configuration.config.ConfigurationExecutionError: \
martian.error.GrokError: Undefined permission 'doesnt.exist' in <class \
'grokcore.security.tests.base.security.missing_permission.MissingPermission'>. \
Use grok.Permission first.
"""  # noqa: E501 line too long
import grokcore.security as grok


class MissingPermission(grok.Context):
    grok.require('doesnt.exist')
