from grokcore import view as grok
from grokcore.view.tests.functional.static.notemplates_overridestatic.original.original import \
    CaveView  # noqa: E501 line too long


class StaticResource(grok.DirectoryResource):
    grok.name('grokcore.view.tests.functional.static'
              '.notemplates_overridestatic.override')
    grok.path('static')


class PalaceView(CaveView):
    pass
