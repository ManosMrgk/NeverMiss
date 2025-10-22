LOCATION_CHOICES = [
    ("Αττική", ".area1"),
    ("Αχαΐα", ".area1012"),
    ("Δράμα", ".area1016"),
    ("Ηράκλειο", ".area1029"),
    ("Θεσσαλονίκη", ".area1060"),
    ("Ιωάννινα", ".area1031"),
    ("Καστοριά", ".area1034"),
    ("Λάρισα", ".area1039"),
    ("Μαγνησία", ".area1042"),
    ("Μεσσηνία", ".area1043"),
    ("Ξάνθη", ".area1044"),
    ("Ροδόπη", ".area1049"),
    ("Χανιά", ".area1057"),
]
LABEL_BY_VALUE = {v: lbl for (lbl, v) in LOCATION_CHOICES}
LOCATION_VALUES = set(LABEL_BY_VALUE.keys())