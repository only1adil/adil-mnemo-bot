#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

with open('words.json', 'r', encoding='utf-8') as f:
    words = json.load(f)

print("First 10 words associations check:\n")
for i, word in enumerate(words[:10]):
    print(f"{i+1}. {word['word']}")
    print(f"   Association: {word['association']}")
    print(f"   Example: {word['example']}\n")
