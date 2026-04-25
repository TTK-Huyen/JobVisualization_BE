try:
    import run_etl_pipeline
    print('run_etl_pipeline import OK')
except Exception as e:
    print('run_etl_pipeline import ERROR:', type(e).__name__, e)
