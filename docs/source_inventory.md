# Source Inventory

The source inventory is defined in `config/sources.yaml`.

Each source entry declares:

- source id
- source kind
- direct or Google competitor layer
- parser
- priority
- enabled flag

This keeps the inventory explicit, inspectable, and easy to extend without hiding source behavior in code.
