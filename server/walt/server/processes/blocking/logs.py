def stream_db_logs(db, logs_handler, **params):
    # ensure all past logs are commited
    db.commit()
    # let the logs handler start buffering realtime logs
    logs_handler.notify_history_processing_startup()
    db.commit()
    # create a server cursor
    cursor_name = db.create_server_logs_cursor(**params)
    # start streaming db logs
    while True:
        record = db.step_server_cursor(cursor_name)
        if record is None:
            break
        d = record._asdict()
        if logs_handler.write_to_client(issuers_filtered=True, **d) is False:
            break
    # delete server cursor
    db.delete_server_cursor(cursor_name)
    # notify history dump is complete
    logs_handler.notify_history_processed()
