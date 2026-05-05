"""
sitecustomize.py — corre automáticamente al startup de Python si está
en sys.path o en site-packages.

Workaround para el bug de Python 3.14 dataclasses._is_type:
    File "/usr/local/lib/python3.14/dataclasses.py", line 814, in _is_type
        ns = sys.modules.get(cls.__module__).__dict__
    AttributeError: 'NoneType' object has no attribute '__dict__'

El bug se dispara cuando un @dataclass es decorado mientras su módulo
todavía está siendo cargado (sys.modules tiene None temporalmente).
Streamlit Cloud sigue corriendo Python 3.14 a pesar del pin a 3.12 en
runtime.txt, así que parcheamos para evitar el AttributeError.

Si Python es 3.13 o anterior, este archivo no hace nada.
"""
import sys

if sys.version_info >= (3, 14):
    try:
        import dataclasses as _dc
        _orig_is_type = getattr(_dc, "_is_type", None)
        if _orig_is_type is not None and not getattr(_dc, "_is_type_patched", False):
            def _safe_is_type(annotation, cls, a_module, a_type,
                              is_type_predicate):
                try:
                    return _orig_is_type(
                        annotation, cls, a_module, a_type, is_type_predicate)
                except AttributeError:
                    return False
            _dc._is_type = _safe_is_type
            _dc._is_type_patched = True
    except Exception:
        pass
