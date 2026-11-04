"""Independent Streamlit Cloud startup diagnostic, WITHOUT broker or AI secrets."""
import sys
import streamlit as st

st.set_page_config(page_title="FOKU$ DIAGNOSTYKA", page_icon="🩺", layout="centered")
st.title("🩺 FOKU$ THE BEST TRADER — TEST URUCHOMIENIA")
st.success("Streamlit uruchomił skrypt i przesłał interfejs do przeglądarki.")
st.write("Python:", sys.version.split()[0])
st.write("Streamlit:", st.__version__)
st.info("Ten ekran nie pobiera świec, nie uruchamia GPT i nie odczytuje kluczy API.")
if st.button("Test interakcji"):
    st.success("Przycisk działa. Połączenie przeglądarki z aplikacją jest aktywne.")
