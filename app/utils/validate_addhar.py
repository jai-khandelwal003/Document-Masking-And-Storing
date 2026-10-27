# Verhoeff tables
d = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]

p = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]

inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]

# Validate using the Verhoeff algorithm
def verhoeff_validate(aadhaar_number):
    try:
        aadhaar = [int(char) for char in aadhaar_number]
    except ValueError:
        return False

    checksum_digit = aadhaar[-1]
    aadhaar = aadhaar[:-1]
    c = 0

    for i, digit in enumerate(reversed(aadhaar)):
        c = d[c][p[(i + 1) % 8][digit]]

    return inv[c] == checksum_digit

# Reverse a list (not needed explicitly in Python as reversed() is available)
def reverse_slice(numbers):
    return list(reversed(numbers))

# Validate Aadhaar number length, format, and checksum
def is_valid_aadhaar(doc_number):
    if len(doc_number) != 12:
        return False

    if not doc_number.isdigit():
        return False

    return verhoeff_validate(doc_number)
