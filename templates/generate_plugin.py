import argparse
import os
import sys
import yaml
import jinja2


def load_yaml(yaml_path):
    """Load and validate YAML input file."""
    try:
        with open(yaml_path, "r") as f:
            config = yaml.safe_load(f)
            if not config or "plugin" not in config or "name" not in config["plugin"]:
                raise ValueError("Invalid YAML: Must contain 'plugin' with 'name'")
            return config
    except FileNotFoundError:
        print(f"Error: YAML file '{yaml_path}' not found")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"Validation error: {e}")
        sys.exit(1)


def generate_descriptor_init(schema, var_name, indent_level=0):
    indent = "   " * indent_level
    code = ""
    kind = schema.get("kind", "").lower()
    if kind == "basic":
        basic_type = schema.get("basic", "").upper()
        code += f"{indent}static Blizzard__Descriptor__Descriptor {var_name} = BLIZZARD__DESCRIPTOR__DESCRIPTOR__INIT;\n"
        code += f"{indent}{var_name}.kind_case = BLIZZARD__DESCRIPTOR__DESCRIPTOR__KIND_BASIC;\n"
        code += f"{indent}{var_name}.basic = BLIZZARD__DESCRIPTOR__BASIC_TYPES__{basic_type};\n"
    elif kind == "list":
        code += f"{indent}static Blizzard__Descriptor__Descriptor {var_name} = BLIZZARD__DESCRIPTOR__DESCRIPTOR__INIT;\n"
        items_schema = schema.get("list", {}).get("items", {})
        list_var = f"{var_name}_list"
        items_var = f"{var_name}_items"
        code += f"{indent}static Blizzard__Descriptor__List {list_var} = BLIZZARD__DESCRIPTOR__LIST__INIT;\n"
        code += generate_descriptor_init(items_schema, items_var, indent_level)
        code += f"{indent}{list_var}.items = &{items_var};\n"
        code += f"{indent}{var_name}.list = &{list_var};\n"
        code += f"{indent}{var_name}.kind_case = BLIZZARD__DESCRIPTOR__DESCRIPTOR__KIND_LIST;\n"
    elif kind == "object":
        code += f"{indent}static Blizzard__Descriptor__Descriptor {var_name} = BLIZZARD__DESCRIPTOR__DESCRIPTOR__INIT;\n"
        properties = schema.get("object", {}).get("properties", {})
        object_var = f"{var_name}_object"
        entries_var = f"{var_name}_entries"
        code += f"{indent}static Blizzard__Descriptor__Object {object_var} = BLIZZARD__DESCRIPTOR__OBJECT__INIT;\n"
        entry_list = []
        for i, (prop_key, prop_schema) in enumerate(properties.items()):
            entry_var = f"{var_name}_prop_{i}"
            value_var = f"{var_name}_value_{i}"
            code += f"{indent}static Blizzard__Descriptor__Object__PropertiesEntry {entry_var} = BLIZZARD__DESCRIPTOR__OBJECT__PROPERTIES_ENTRY__INIT;\n"
            code += f'{indent}{entry_var}.key = "{prop_key}";\n'
            code += generate_descriptor_init(prop_schema, value_var, indent_level)
            code += f"{indent}{entry_var}.value = &{value_var};\n"
            entry_list.append(f"&{entry_var}")
        code += f"{indent}static Blizzard__Descriptor__Object__PropertiesEntry* {entries_var}[] = {{{', '.join(entry_list)}}};\n"
        code += f"{indent}{object_var}.n_properties = sizeof({entries_var}) / sizeof({entries_var}[0]);\n"
        code += f"{indent}{object_var}.properties = {entries_var};\n"
        code += f"{indent}{var_name}.object = &{object_var};\n"
        code += f"{indent}{var_name}.kind_case = BLIZZARD__DESCRIPTOR__DESCRIPTOR__KIND_OBJECT;\n"
    elif kind == "optional":
        code += f"{indent}static Blizzard__Descriptor__Descriptor {var_name} = BLIZZARD__DESCRIPTOR__DESCRIPTOR__INIT;\n"
        item_schema = schema.get("optional", {}).get("item", {})
        optional_var = f"{var_name}_optional"
        item_var = f"{var_name}_item"
        code += f"{indent}static Blizzard__Descriptor__Optional {optional_var} = BLIZZARD__DESCRIPTOR__OPTIONAL__INIT;\n"
        code += generate_descriptor_init(item_schema, item_var, indent_level)
        code += f"{indent}{optional_var}.item = &{item_var};\n"
        code += f"{indent}{var_name}.optional = &{optional_var};\n"
        code += f"{indent}{var_name}.kind_case = BLIZZARD__DESCRIPTOR__DESCRIPTOR__KIND_OPTIONAL;\n"
    else:
        raise ValueError(f"Unknown schema kind: {kind}")

    return code


def pack_any_code(var_name, descriptor_var, indent_level=0):
    indent = "   " * indent_level
    buf_var = f"{var_name}_buf"
    size_var = f"{var_name}_size"
    code = f"{indent}size_t {size_var} = blizzard__descriptor__descriptor__get_packed_size(&{descriptor_var});\n"
    code += f"{indent}if ({size_var} > sizeof({buf_var})) {{\n"
    code += f'{indent}   perror("Buffer too small");\n'
    code += f"{indent}   return NULL;\n"
    code += f"{indent}}}\n"
    code += f"{indent}blizzard__descriptor__descriptor__pack(&{descriptor_var}, {buf_var});\n"
    code += f'{indent}{var_name}.type_url = "type.googleapis.com/blizzard.descriptor.Descriptor";\n'
    code += f"{indent}{var_name}.value.len = {size_var};\n"
    code += f"{indent}{var_name}.value.data = {buf_var};\n"
    return code


def generate_value_unpack_code(schema, value_var, output_var_prefix, indent_level=0):
    """Recursively generate C code to unpack a Blizzard__Value__Value based on schema."""
    indent = "   " * indent_level
    code = ""
    params = []
    kind = schema.get("kind", "").lower()

    if kind == "basic":
        basic_type = schema.get("basic", "").lower()
        if basic_type == "integer":
            code += f"{indent}if ({value_var} && {value_var}->kind_case == BLIZZARD__VALUE__VALUE__KIND_INTEGER) {{\n"
            code += f"{indent}   int64_t {output_var_prefix} = {value_var}->integer;\n"
            code += f"{indent}}} else {{\n"
            code += (
                f'{indent}   send_error_response(sock, id, "Expected integer value");\n'
            )
            code += f"{indent}   return;\n"
            code += f"{indent}}}\n"
            return code, [["int64_t", output_var_prefix]]
        elif basic_type == "string":
            code += f"{indent}char* {output_var_prefix} = NULL;\n"
            code += f"{indent}if ({value_var} && {value_var}->kind_case == BLIZZARD__VALUE__VALUE__KIND_STRING) {{\n"
            code += f"{indent}   {output_var_prefix} = strdup({value_var}->string);\n"
            code += f"{indent}}} else {{\n"
            code += (
                f'{indent}   send_error_response(sock, id, "Expected string value");\n'
            )
            code += f"{indent}   return;\n"
            code += f"{indent}   }}\n"
            return code, [["char*", output_var_prefix]]
        elif basic_type == "any_object":
            code += f"{indent}if ({value_var} && {value_var}->kind_case == BLIZZARD__VALUE__VALUE__KIND_OBJECT) {{\n"
            code += f"{indent}      static Blizzard__Value__Object* {output_var_prefix} = {value_var}->object;\n"
            code += f"{indent}   }} else {{\n"
            code += f'{indent}      send_error_response(sock, id, "Expected object value");\n'
            code += f"{indent}      return;\n"
            code += f"{indent}   }}\n"
            return code, [["Blizzard__Value__Object*", output_var_prefix]]
        else:
            raise ValueError(f"Unsupported basic type: {basic_type}")
    elif kind == "list":
        items_schema = schema.get("list", {}).get("items", {})
        items_var = f"{output_var_prefix}_items"
        n_var = f"n_{items_var}"
        code += f"{indent}size_t {n_var} = 0;\n"
        code += f"{indent}char** {items_var} = NULL;\n"
        code += f"{indent}if ({value_var} && {value_var}->kind_case == BLIZZARD__VALUE__VALUE__KIND_LIST) {{\n"
        code += f"{indent}   Blizzard__Value__List* list = {value_var}->list;\n"
        code += f"{indent}   {n_var} = list->n_elements;\n"
        item_code, item_params = generate_value_unpack_code(
            items_schema, "list->elements[i]", "temp_item", indent_level + 1
        )
        item_type = item_params[0][0] if item_params else "void*"
        code += f"{indent}   {items_var} = malloc({n_var} * sizeof({item_type}));\n"
        code += f"{indent}   if (!{items_var}) {{\n"
        code += f'{indent}      send_error_response(sock, id, "Malloc failed for list items");\n'
        code += f"{indent}      return;\n"
        code += f"{indent}   }}\n"
        code += f"{indent}   for (size_t i = 0; i < {n_var}; i++) {{\n"
        code += item_code.replace("return;", "continue;")
        code += f"{indent}      {items_var}[i] = temp_item;\n"
        code += f"{indent}   }}\n"
        code += f"{indent}}} else {{\n"
        code += f'{indent}   send_error_response(sock, id, "Expected list value");\n'
        code += f"{indent}   return;\n"
        code += f"{indent}}}\n"
        return code, [["size_t", n_var], [f"{item_type}*", items_var]]
    elif kind == "object":
        properties = schema.get("object", {}).get("properties", {})
        code += f"{indent}if ({value_var} && {value_var}->kind_case == BLIZZARD__VALUE__VALUE__KIND_OBJECT) {{\n"
        code += f"{indent}   Blizzard__Value__Object* obj = {value_var}->object;\n"
        params = []
        for prop_key, prop_schema in properties.items():
            prop_var = f"{output_var_prefix}_{prop_key}"
            code += f"{indent}   Blizzard__Value__Value* {prop_var}_value = NULL;\n"
            code += f"{indent}   for (size_t i = 0; i < obj->n_children; i++) {{\n"
            code += f'{indent}      if (strcmp(obj->children[i]->key, "{prop_key}") == 0) {{\n'
            code += f"{indent}         {prop_var}_value = obj->children[i]->value;\n"
            code += f"{indent}         break;\n"
            code += f"{indent}      }}\n"
            code += f"{indent}   }}\n"
            code += f"{indent}   if (!{prop_var}_value) {{\n"
            code += f'{indent}      send_error_response(sock, id, "Missing property {prop_key}");\n'
            code += f"{indent}      return;\n"
            code += f"{indent}   }}\n"
            prop_code, prop_params = generate_value_unpack_code(
                prop_schema, f"{prop_var}_value", prop_var, indent_level + 1
            )
            code += prop_code
            params.extend(prop_params)
        code += f"{indent}}} else {{\n"
        code += f'{indent}   send_error_response(sock, id, "Expected object value");\n'
        code += f"{indent}   return;\n"
        code += f"{indent}}}\n"
        return code, params
    elif kind == "optional":
        item_schema = schema.get("optional", {}).get("item", {})
        code += f"{indent}if ({value_var} && {value_var}->kind_case != BLIZZARD__VALUE__VALUE__KIND__NOT_SET) {{\n"
        item_code, item_params = generate_value_unpack_code(
            item_schema, value_var, output_var_prefix, indent_level + 1
        )
        code += item_code
        code += f"{indent}}} else {{\n"
        code += f"{indent}   // Optional not set\n"
        code += f"{indent}   {item_params[0][0]} {output_var_prefix} = { 'NULL' if '*' in item_params[0][0] else '0' };\n"
        code += f"{indent}}}\n"
        return code, [[item_params[0][0], output_var_prefix]]
    else:
        raise ValueError(f"Unknown schema kind: {kind}")


def generate_value_pack_code(schema, value_var, output_any_var, indent_level=0):
    indent = "   " * indent_level
    code = f"Blizzard__Value__Value {output_any_var}_value = BLIZZARD__VALUE__VALUE__INIT;\n"
    kind = schema.get("kind", "").lower()

    if kind == "basic":
        basic_type = schema.get("basic", "").lower()
        if basic_type == "integer":
            code += f"{indent}{output_any_var}_value.kind_case = BLIZZARD__VALUE__VALUE__KIND_INTEGER;\n"
            code += f"{indent}{output_any_var}_value.integer = {value_var};\n"
        elif basic_type == "string":
            code += f"{indent}{output_any_var}_value.kind_case = BLIZZARD__VALUE__VALUE__KIND_STRING;\n"
            code += f"{indent}{output_any_var}_value.string = strdup({value_var});\n"
        elif basic_type == "any_object":
            code += f"{indent}{output_any_var}_value.kind_case = BLIZZARD__VALUE__VALUE__KIND_OBJECT;\n"
            code += f"{indent}{output_any_var}_value.object = {value_var};\n"
        else:
            raise ValueError(f"Unsupported basic type for packing: {basic_type}")
    elif kind == "list":
        raise NotImplementedError("List result packing not implemented")
    elif kind == "object":
        raise NotImplementedError("Object result packing not implemented")
    elif kind == "optional":
        raise NotImplementedError("Optional result packing not implemented")

    code += f"{indent}size_t {output_any_var}_size = blizzard__value__value__get_packed_size(&{output_any_var}_value);\n"
    code += f"{indent}uint8_t* {output_any_var}_buf = malloc({output_any_var}_size);\n"
    code += f"{indent}if (!{output_any_var}_buf) {{\n"
    code += f'{indent}   send_error_response(sock, id, "Malloc failed for response buffer");\n'
    code += f"{indent}   return;\n"
    code += f"{indent}}}\n"
    code += f"{indent}blizzard__value__value__pack(&{output_any_var}_value, {output_any_var}_buf);\n"
    code += f"{indent}Google__Protobuf__Any* {output_any_var} = malloc(sizeof(Google__Protobuf__Any));\n"
    code += f"{indent}google__protobuf__any__init({output_any_var});\n"
    code += f'{indent}{output_any_var}->type_url = "type.googleapis.com/blizzard.value.Value";\n'
    code += f"{indent}{output_any_var}->value.len = {output_any_var}_size;\n"
    code += f"{indent}{output_any_var}->value.data = {output_any_var}_buf;\n"
    return code


def outparam_shape(r):
    # For strings/bytes we pass ** so the callee can allocate (strdup/malloc)
    if r.get("set_func") == "rbusValue_SetString":
        return {"out_ctype": "char**", "call_arg": f"&{r['name']}", "needs_len": False}
    if r.get("set_func") == "rbusValue_SetBytes":
        return {"out_ctype": "uint8_t**", "call_arg": f"&{r['name']}", "needs_len": True}

    # For types that want an address in setter (e.g., time)
    if r.get("pass_addr"):
        return {"out_ctype": f"{r['ctype']}*", "call_arg": f"&{r['name']}", "needs_len": False}

    # Default: pointer to the ctype (covers ints, floats, bool, etc.)
    return {"out_ctype": f"{r['ctype']}*", "call_arg": f"&{r['name']}", "needs_len": False}

def classify_basic(b):
    b = (b or "").lower()
    if b == "string":
        return "string"
    if b in ("int8", "int16", "int32", "int64", "sint32", "sint64", "int"):
        return "int"  # signed integer family
    if b in ("uint8", "uint16", "uint32", "uint64"):
        return "uint"  # unsigned integer family
    return None

def conv_for_input(schema):
    s = schema or {}
    if (s.get("kind") or "").lower() == "basic":
        b = (s.get("basic") or "").lower()
        cls = classify_basic(b)
        table = {
            "boolean": ("bool", "rbusValue_GetBoolean({v})", None),
            "integer": ("int64_t", "rbusValue_GetInt64({v})", "int"),
            "double": ("double", "rbusValue_GetDouble({v})", None),
            "string": ("char const*", "rbusValue_GetString({v}, NULL)", "string"),
            "bytes": ("uint8_t const*", "rbusValue_GetBytes({v}, NULL)", None),
            "any_object": ("rbusObject_t", "rbusValue_GetObject({v})", None),
            "object": ("rbusObject_t", "rbusValue_GetObject({v})", None),
        }
        if b in table:
            ctype, expr, tclass = table[b]
            return {"ctype": ctype, "expr": expr, "type_class": tclass}
    if (s.get("kind") or "").lower() == "object":
        return {
            "ctype": "rbusObject_t",
            "expr": "rbusValue_GetObject({v})",
            "type_class": None,
        }
    return {"ctype": None, "expr": None, "type_class": None}

def conv_for_result(schema):
    s = schema or {}
    kind = (s.get("kind") or "").lower()
    if kind == "basic":
        b = (s.get("basic") or "").lower()
        tclass = classify_basic(b)
        table = {
            "boolean": dict(
                ctype="bool", init="false", set_func="rbusValue_SetBoolean"
            ),
            "integer": dict(
                ctype="int64_t",
                init="0",
                set_func="rbusValue_SetInt64",
                type_class="int",
            ),
            "double": dict(ctype="double", init="0", set_func="rbusValue_SetDouble"),
            "string": dict(
                ctype="char*",
                init="NULL",
                set_func="rbusValue_SetString",
                needs_free=True,
                type_class="string",
            ),
            "bytes": dict(
                ctype="uint8_t*",
                init="NULL",
                set_func="rbusValue_SetBytes",
                needs_len=True,
                needs_free=True,
            ),
            "object": dict(
                ctype="rbusObject_t", init="NULL", set_func="rbusValue_SetObject"
            ),
        }
        if b in table:
            d = table[b].copy()
            d.setdefault("type_class", tclass)
            d.setdefault("needs_len", False)
            d.setdefault("needs_free", False)
            d.setdefault("pass_addr", False)
            return d
    if kind == "object":
        return dict(ctype="rbusObject_t", init="NULL", set_func="rbusValue_SetObject")
    return dict(ctype="rbusValue_t", init=None, set_func=None)


def process_schemas(config):
    """Pre-process schemas to generate C init and unpack code for descriptors."""
    processed_methods = []
    for idx, method in enumerate(config.get("methods", [])):
        method_copy = method.copy()
        param_schema = method.get("parameters_schema", {})
        result_schema = method.get("result_schema", {})

        # Descriptor initialization
        param_var = f"method_{idx}_param_desc"
        method_copy["param_init_code"] = generate_descriptor_init(
            param_schema, param_var, indent_level=1
        )
        method_copy["param_pack_code"] = pack_any_code(
            f"method_{idx}_param_any", param_var, indent_level=1
        )

        result_var = f"method_{idx}_result_desc"
        method_copy["result_init_code"] = generate_descriptor_init(
            result_schema, result_var, indent_level=1
        )
        method_copy["result_pack_code"] = pack_any_code(
            f"method_{idx}_result_any", result_var, indent_level=1
        )

        # Parameter unpacking
        unpack_code, params = generate_value_unpack_code(
            param_schema, "params", f"{method['name']}_param", indent_level=0
        )
        method_copy["param_unpack_code"] = unpack_code
        method_copy["params"] = params

        # Result packing
        # pack_code = generate_value_pack_code(
        #    result_schema, f"{method['name']}_result", "success_any", indent_level=1
        # )
        # method_copy["result_pack_code"] = pack_code

        # Interface return type
        method_copy["return_type"] = (
            "Blizzard__Value__Object*"
            if result_schema.get("kind") == "basic"
            and result_schema.get("basic") == "any_object"
            else result_schema.get("basic", "void")
        )

        processed_methods.append(method_copy)

        for m in processed_methods:
            # inputs
            iprops = (m.get("parameters_schema", {}) or {}).get("object", {}).get(
                "properties", {}
            ) or {}
            m["props"] = []
            for name, schema in iprops.items():
                conv = conv_for_input(schema)
                m["props"].append(
                    {
                        "name": name,
                        "ctype": conv["ctype"],
                        "expr": conv["expr"],
                        "type_class": conv[
                            "type_class"
                        ],
                    }
                )

            # outputs
            rs = m.get("result_schema") or {}
            m["results"] = []
            if (rs.get("kind") or "").lower() == "object":
                rprops = (rs.get("object") or {}).get("properties", {}) or {}
                for name, schema in rprops.items():
                    dc = conv_for_result(schema)
                    m["results"].append({"name": name, **dc})
            else:
                dc = conv_for_result(rs)
                m["results"].append({"name": "result", **dc})

            # --- auto-wire by TYPE (string/integer), not by name --------------------
            for r in m["results"]:
                r["auto_from"] = None
                if r.get("type_class") in ("string", "int", "uint"):
                    match = next(
                        (p for p in m["props"] if p["type_class"] == r["type_class"]),
                        None,
                    )
                    if match:
                        r["auto_from"] = match["name"]

            for r in m["results"]:
               shape = outparam_shape(r)
               r["out_ctype"] = shape["out_ctype"]
               r["call_arg"]  = shape["call_arg"]
               r["len_param"] = None
               if r.get("needs_len") or shape["needs_len"]:
                     r["len_param"] = {"ctype": "int*", "name": f"{r['name']}_len", "call_arg": f"&{r['name']}_len"}

    config["processed_methods"] = processed_methods
    return config


def generate_plugin(input_yaml_path, output_dir, language):
    """Generate plugin template files from YAML and templates."""

    if language not in ["c", "cpp"]:
        raise ValueError("Unsupported language: Must be 'c' or 'cpp'")

    config = load_yaml(input_yaml_path)
    config = process_schemas(config)

    template_subdir = language
    template_dir = os.path.join(os.path.dirname(__file__), "tmpl", template_subdir)

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    plugin_name = ((config.get("plugin") or {}).get("name") or "").lower()

    templates = {
        "c": [
            ("plugin.c.j2", f"{plugin_name}_plugin.c"),
            ("impl.c.j2", f"{plugin_name}_impl.c"),
            ("impl.h.j2", f"{plugin_name}_impl.h"),
            ("CMakeLists.txt.j2", "CMakeLists.txt"),
        ],
        "cpp": [
            ("plugin.cpp.j2", f"{plugin_name}_plugin.cpp"),
            ("CMakeLists.txt.j2", "CMakeLists.txt"),
        ],
    }[language]

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    generated_files = []
    for template_name, output_filename in templates:
        try:
            template = env.get_template(template_name)
            output_path = os.path.join(output_dir, output_filename)
            with open(output_path, "w") as f:
                f.write(
                    template.render(
                        plugin=config["plugin"],
                        methods=config.get("processed_methods", []),
                        plugin_name=plugin_name,
                    )
                )
            generated_files.append(output_path)
        except jinja2.TemplateNotFound:
            print(f"Error: Template '{template_name}' not found in '{template_dir}'")
            sys.exit(1)
        except Exception as e:
            print(f"Error rendering template '{template_name}': {e}")
            sys.exit(1)

    return f"Generated files: {', '.join(generated_files)}"


def main():
    parser = argparse.ArgumentParser(
        description="Generate Blizzard plugin template files"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to input YAML file",
    )
    parser.add_argument(
        "--language",
        required=False,
        default="c",
    )
    parser.add_argument(
        "--output-dir",
        default="./generated",
        help="Output directory for generated files",
    )
    args = parser.parse_args()

    result = generate_plugin(args.input, args.output_dir, args.language)
    print(result)


if __name__ == "__main__":
    main()
