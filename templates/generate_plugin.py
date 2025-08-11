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


def result_conv(schema):
    """
    Map YAML schema -> result variable declaration and setter info.
    Returns a dict with:
      - ctype: C type for the result variable
      - init: initializer (string placed after '='), or None for no initializer
      - set_func: rbusValue_Set* function name
      - needs_len: True if a <name>_len int should be declared (bytes)
      - pass_addr: True if setter expects an address (&var) instead of var (time)
      - needs_free: True if you likely malloc and should free after setting (string/bytes)
    """
    s = schema or {}
    kind = (s.get("kind") or "").lower()

    if kind == "basic":
        b = (s.get("basic") or "").lower()
        table = {
            "boolean": dict(
                ctype="bool", init="false", set_func="rbusValue_SetBoolean"
            ),
            "bool": dict(ctype="bool", init="false", set_func="rbusValue_SetBoolean"),
            "char": dict(ctype="char", init="'\\0'", set_func="rbusValue_SetChar"),
            "byte": dict(ctype="unsigned char", init="0", set_func="rbusValue_SetByte"),
            "int8": dict(ctype="int8_t", init="0", set_func="rbusValue_SetInt8"),
            "uint8": dict(ctype="uint8_t", init="0", set_func="rbusValue_SetUInt8"),
            "int16": dict(ctype="int16_t", init="0", set_func="rbusValue_SetInt16"),
            "uint16": dict(ctype="uint16_t", init="0", set_func="rbusValue_SetUInt16"),
            "int32": dict(ctype="int32_t", init="0", set_func="rbusValue_SetInt32"),
            "sint32": dict(ctype="int32_t", init="0", set_func="rbusValue_SetInt32"),
            "uint32": dict(ctype="uint32_t", init="0", set_func="rbusValue_SetUInt32"),
            "int64": dict(ctype="int64_t", init="0", set_func="rbusValue_SetInt64"),
            "sint64": dict(ctype="int64_t", init="0", set_func="rbusValue_SetInt64"),
            "uint64": dict(ctype="uint64_t", init="0", set_func="rbusValue_SetUInt64"),
            "float": dict(ctype="float", init="0", set_func="rbusValue_SetSingle"),
            "double": dict(ctype="double", init="0", set_func="rbusValue_SetDouble"),
            "time": dict(
                ctype="rbusDateTime_t",
                init=None,
                set_func="rbusValue_SetTime",
                pass_addr=True,
            ),
            "datetime": dict(
                ctype="rbusDateTime_t",
                init=None,
                set_func="rbusValue_SetTime",
                pass_addr=True,
            ),
            "string": dict(
                ctype="char*",
                init="NULL",
                set_func="rbusValue_SetString",
                needs_free=True,
            ),
            "bytes": dict(
                ctype="uint8_t*",
                init="NULL",
                set_func="rbusValue_SetBytes",
                needs_len=True,
                needs_free=True,
            ),
            "any_object": dict(
                ctype="rbusObject_t", init="NULL", set_func="rbusValue_SetObject"
            ),
            "object": dict(
                ctype="rbusObject_t", init="NULL", set_func="rbusValue_SetObject"
            ),
            "property": dict(
                ctype="rbusProperty_t", init="NULL", set_func="rbusValue_SetProperty"
            ),
        }
        if b in table:
            return table[b]

    if kind == "object":
        return dict(ctype="rbusObject_t", init="NULL", set_func="rbusValue_SetObject")

    # Fallback: leave as rbusValue_t
    return dict(ctype="rbusValue_t", init=None, set_func=None)


def conv_for(schema):
    """
    Return {"ctype": <C type>, "expr": <getter expression with {v} placeholder>}
    """
    s = schema or {}
    kind = (s.get("kind") or "").lower()

    if kind == "basic":
        b = (s.get("basic") or "").lower()
        table = {
            "boolean": ("bool", "rbusValue_GetBoolean({v})"),
            "bool": ("bool", "rbusValue_GetBoolean({v})"),
            "char": ("char", "rbusValue_GetChar({v})"),
            "byte": ("unsigned char", "rbusValue_GetByte({v})"),
            "int8": ("int8_t", "rbusValue_GetInt8({v})"),
            "uint8": ("uint8_t", "rbusValue_GetUInt8({v})"),
            "int16": ("int16_t", "rbusValue_GetInt16({v})"),
            "uint16": ("uint16_t", "rbusValue_GetUInt16({v})"),
            "int32": ("int32_t", "rbusValue_GetInt32({v})"),
            "sint32": ("int32_t", "rbusValue_GetInt32({v})"),
            "uint32": ("uint32_t", "rbusValue_GetUInt32({v})"),
            "integer": ("int64_t", "rbusValue_GetInt64({v})"),
            "int64": ("int64_t", "rbusValue_GetInt64({v})"),
            "sint64": ("int64_t", "rbusValue_GetInt64({v})"),
            "uint64": ("uint64_t", "rbusValue_GetUInt64({v})"),
            "float": ("float", "rbusValue_GetSingle({v})"),
            "double": ("double", "rbusValue_GetDouble({v})"),
            "time": ("rbusDateTime_t const*", "rbusValue_GetTime({v})"),
            "datetime": ("rbusDateTime_t const*", "rbusValue_GetTime({v})"),
            "string": ("char const*", "rbusValue_GetString({v}, NULL)"),
            "bytes": ("uint8_t const*", "rbusValue_GetBytes({v}, NULL)"),
            "any_object": ("rbusObject_t", "rbusValue_GetObject({v})"),
            "object": ("rbusObject_t", "rbusValue_GetObject({v})"),
            "property": ("rbusProperty_t", "rbusValue_GetProperty({v})"),
        }
        if b in table:
            ctype, expr = table[b]
            return {"ctype": ctype, "expr": expr}

    if kind == "object":
        return {"ctype": "rbusObject_t", "expr": "rbusValue_GetObject({v})"}

    # Fallback: keep as rbusValue_t with no conversion
    return {"ctype": None, "expr": None}


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
            props = (
                m.get("parameters_schema", {}).get("object", {}).get("properties", {})
                or {}
            )
            m["props"] = []
            for name, schema in props.items():
                conv = conv_for(schema)
                m["props"].append(
                    {
                        "name": name,
                        "ctype": conv["ctype"],
                        "expr": conv["expr"],  # includes {v} placeholder
                        "schema": schema,
                    }
                )
                rs = m.get("result_schema") or {}
                rkind = (rs.get("kind") or "").lower()
                m["results"] = []
                if rkind == "object":
                    props = (rs.get("object") or {}).get("properties") or {}
                    for name, schema in props.items():
                        conv = result_conv(schema)
                        conv.setdefault("needs_len", False)
                        conv.setdefault("pass_addr", False)
                        conv.setdefault("needs_free", False)
                        m["results"].append({"name": name, **conv})
                else:
                    # Single (non-object) result; expose it as "result"
                    conv = result_conv(rs)
                    conv.setdefault("needs_len", False)
                    conv.setdefault("pass_addr", False)
                    conv.setdefault("needs_free", False)
                    m["results"].append({"name": "result", **conv})

    config["processed_methods"] = processed_methods
    return config


def generate_plugin(input_yaml_path, output_dir, plugin_name, language):
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

    templates = {
        "c": [
            ("plugin.c.j2", f"{plugin_name}_plugin.c"),
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
    parser.add_argument(
        "--plugin-name",
        required=True,
        help="Name of the plugin (used in filenames)",
    )
    args = parser.parse_args()

    result = generate_plugin(
        args.input, args.output_dir, args.plugin_name, args.language
    )
    print(result)


if __name__ == "__main__":
    main()
