from walt.server.tools import np_record_to_dict


DB_LOGS_BLOCK_SIZE = 128


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
        rows = db.step_server_cursor(cursor_name, DB_LOGS_BLOCK_SIZE)
        if rows.size == 0:  # end of stream detected
            break
        if logs_handler.write_db_logs_to_client(rows) is False:
            break
        if rows.size < DB_LOGS_BLOCK_SIZE:  # end of stream detected
            break
    # delete server cursor
    db.delete_server_cursor(cursor_name)
    # notify history dump is complete
    logs_handler.notify_history_processed()
