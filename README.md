# Iraq School Content

Educational content repository for the Iraq School app.

## Structure

```
books/
├── {stage}/
│   ├── {grade}/
│   │   ├── {subject}/
│   │   │   ├── metadata.json   # Book details + chapters
│   │   │   ├── book.pdf         # Full book PDF
│   │   │   └── cover.png        # Cover image
│   │   └── ...
│   └── ...
└── ...

books.json           # Master index
subjects.json        # Subject list per stage
```

## Stages

| ID | Arabic | Grades |
|----|--------|--------|
| primary | المرحلة الابتدائية | 1-6 |
| intermediate | المرحلة المتوسطة | 1-3 |
| preparatory | المرحلة الإعدادية | 4-6 |

## How to Add a Book

1. Create folder `books/{stage}/{grade}/{subject}/`
2. Add `metadata.json`, `book.pdf`, `cover.png`
3. Add entry in `books.json`
4. Commit and push to `main`

## License

All content belongs to the Iraqi Ministry of Education.
