def safe_list_get(list, index, default=None):
    try:
        return list[index]
    except IndexError:
        return default

