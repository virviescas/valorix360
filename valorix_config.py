import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


def _streamlit_secrets():
    try:
        return dict(st.secrets)
    except StreamlitSecretNotFoundError:
        return {}


def config_value(name, default=None):
    if name in os.environ:
        return os.environ[name]
    return _streamlit_secrets().get(name, default)