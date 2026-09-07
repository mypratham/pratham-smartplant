import grokcore.site


class Fireplace:
    pass


class Cave(grokcore.site.Site):
    grokcore.site.local_utility(Fireplace)
