__all__ = ['WorldService']


def __getattr__(name):
    if name == 'WorldService':
        from backend.world.service import WorldService
        return WorldService
    raise AttributeError(name)
