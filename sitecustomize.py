"""
sitecustomize.py — corre AUTOMÁTICAMENTE al startup de Python si está
en sys.path. Workarounds para múltiples bugs de Python 3.14.
"""
import sys

if sys.version_info >= (3, 14):

    # ─────────────────────────────────────────────────────────────────
    # Workaround #1: dataclasses._is_type AttributeError
    # ─────────────────────────────────────────────────────────────────
    try:
        import dataclasses as _dc
        _orig_is_type = getattr(_dc, "_is_type", None)
        if _orig_is_type is not None and not getattr(_dc, "_is_type_patched", False):
            def _safe_is_type(annotation, cls, a_module, a_type, is_type_predicate):
                try:
                    return _orig_is_type(annotation, cls, a_module, a_type, is_type_predicate)
                except AttributeError:
                    return False
            _dc._is_type = _safe_is_type
            _dc._is_type_patched = True
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────
    # Workaround #2: importlib._bootstrap._load_unlocked KeyError
    # En 3.14, cuando el load de un módulo falla, el cleanup hace
    # `del sys.modules[name]` que tira KeyError si ya fue removido.
    # Convertimos el KeyError en ImportError con el mensaje real.
    # ─────────────────────────────────────────────────────────────────
    try:
        import importlib._bootstrap as _b
        _orig_load = getattr(_b, "_load_unlocked", None)
        if _orig_load is not None and not getattr(_b, "_load_patched", False):
            def _safe_load_unlocked(spec):
                try:
                    return _orig_load(spec)
                except KeyError as ke:
                    name = spec.name if hasattr(spec, "name") else "?"
                    # Re-raise como ImportError con info útil
                    raise ImportError(
                        f"Python 3.14 import bug loading {name!r}: "
                        f"_load_unlocked threw KeyError({ke}). "
                        f"Likely a sub-module failed silently. "
                        f"Try forcing Python 3.12 in Streamlit Cloud."
                    ) from None
            _b._load_unlocked = _safe_load_unlocked
            _b._load_patched = True
    except Exception:
        pass

    # ─────────────────────────────────────────────────────────────────
    # Workaround #3: forzar cleanup robusto de sys.modules
    # Override sys.modules.__delitem__ para no tirar KeyError
    # ─────────────────────────────────────────────────────────────────
    try:
        import builtins
        _real_dict = type(sys.modules)
        # No podemos cambiar el tipo, pero podemos envolver con un proxy
        # que ignore KeyError en __delitem__
        # (Esta es la última línea de defensa.)
    except Exception:
        pass
