@echo off
if not exist .venv ( py -m venv .venv )
call .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app_valorix.py
