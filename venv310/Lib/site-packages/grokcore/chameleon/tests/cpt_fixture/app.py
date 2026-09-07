import grokcore.view
import grokcore.viewlet
from grokcore.component.interfaces import IContext
from zope.container.btree import BTreeContainer
from zope.interface import implementer

from grokcore.chameleon import components


@implementer(IContext)
class Mammoth(BTreeContainer):
    pass


class CavePainting(grokcore.view.View):
    pass


class Food(grokcore.view.View):

    text = "<ME GROK EAT MAMMOTH!>"

    def me_do(self):
        return self.text


class Inline(grokcore.view.View):
    sometext = 'Some Text'


inline = components.ChameleonPageTemplate(
    "<html><body>ME GROK HAS INLINES! ${view.sometext}</body></html>")


class Vars(grokcore.view.View):
    pass


class Expressions(grokcore.view.View):
    pass


class MainArea(grokcore.viewlet.ViewletManager):
    grokcore.viewlet.name('main')


class MainContent(grokcore.viewlet.Viewlet):
    grokcore.viewlet.view(Expressions)
    grokcore.viewlet.viewletmanager(MainArea)

    def render(self):
        return 'Hello from viewlet'


class MacroMaster(grokcore.view.View):
    """A view with a template that contains macro defs."""


class MacroUser(grokcore.view.View):
    """A view with a template that uses macros."""


class Namespace(grokcore.view.View):

    def namespace(self):
        return {'myname': 'Henk'}


class Menu(grokcore.view.View):

    variants = ['raw', 'bloody']
