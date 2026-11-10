package com.baypeline.backend.support;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigInteger;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * contracts/schemas 의 JSON Schema 규칙을 Java로 옮긴 구조 검증 헬퍼.
 * 추가 필드·필수 필드 누락·잘못된 타입/Enum은 CONTRACT_VALIDATION_FAILED(400)로 거부한다.
 * null·0·"0"·빈 배열을 서로 구분하기 위해 JsonNode 상태에서 직접 검사한다.
 */
public final class Contract {

    public static final String SCHEMA_VERSION = "0.1.0";

    private static final String BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    private static final Pattern ADDRESS = Pattern.compile("^[1-9A-HJ-NP-Za-km-z]{32,44}$");
    private static final Pattern TIMESTAMP = Pattern.compile("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$");
    private static final Pattern POSITIVE_RAW = Pattern.compile("^[1-9][0-9]*$");
    private static final Pattern VERSION = Pattern.compile(
            "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)"
                    + "(-((0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(\\.(0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
                    + "(\\+[0-9A-Za-z-]+(\\.[0-9A-Za-z-]+)*)?$");

    private Contract() {
    }

    /** 객체이며 required를 모두 갖고, required+optional 외 필드가 없어야 한다. */
    public static JsonNode object(JsonNode node, String path, List<String> required, List<String> optional) {
        if (node == null || !node.isObject()) {
            throw ApiException.contract(path + " must be an object");
        }
        Set<String> allowed = new HashSet<>(required);
        allowed.addAll(optional);
        for (Iterator<String> it = node.fieldNames(); it.hasNext(); ) {
            String name = it.next();
            if (!allowed.contains(name)) {
                throw ApiException.contract(path + "." + name + " is not allowed");
            }
        }
        for (String name : required) {
            if (!node.has(name)) {
                throw ApiException.contract(path + "." + name + " is required");
            }
        }
        return node;
    }

    public static String string(JsonNode node, String path) {
        if (node == null || !node.isTextual()) {
            throw ApiException.contract(path + " must be a string");
        }
        return node.textValue();
    }

    public static String id(JsonNode node, String path) {
        String value = string(node, path);
        if (value.isEmpty()) {
            throw ApiException.contract(path + " must not be empty");
        }
        return value;
    }

    public static String constant(JsonNode node, String path, String expected) {
        String value = string(node, path);
        if (!expected.equals(value)) {
            throw ApiException.contract(path + " must be " + expected);
        }
        return value;
    }

    public static String version(JsonNode node, String path) {
        String value = string(node, path);
        if (!VERSION.matcher(value).matches()) {
            throw ApiException.contract(path + " must be a semantic version");
        }
        return value;
    }

    public static String timestamp(JsonNode node, String path) {
        String value = string(node, path);
        if (!TIMESTAMP.matcher(value).matches()) {
            throw ApiException.contract(path + " must be a UTC ISO 8601 timestamp ending in Z");
        }
        try {
            Instant.parse(value);
        } catch (DateTimeParseException e) {
            throw ApiException.contract(path + " is not a valid date-time");
        }
        return value;
    }

    /** Base58 문자·길이 검사 후 디코딩 결과가 32바이트인지 확인한다. */
    public static String address(JsonNode node, String path) {
        String value = string(node, path);
        if (!ADDRESS.matcher(value).matches() || base58Size(value) != 32) {
            throw ApiException.contract(path + " must be a Solana address");
        }
        return value;
    }

    public static String positiveRawAmount(JsonNode node, String path) {
        String value = string(node, path);
        if (!POSITIVE_RAW.matcher(value).matches()) {
            throw ApiException.contract(path + " must be a positive decimal integer string");
        }
        return value;
    }

    public static String enumValue(JsonNode node, String path, Set<String> values) {
        String value = string(node, path);
        if (!values.contains(value)) {
            throw ApiException.contract(path + " must be one of " + values);
        }
        return value;
    }

    public static boolean bool(JsonNode node, String path) {
        if (node == null || !node.isBoolean()) {
            throw ApiException.contract(path + " must be a boolean");
        }
        return node.booleanValue();
    }

    /** JSON Schema integer: 소수부가 0인 숫자. */
    public static long integer(JsonNode node, String path, long min, long max) {
        if (node == null || !node.isNumber()) {
            throw ApiException.contract(path + " must be an integer");
        }
        long value;
        if (node.isIntegralNumber() && node.canConvertToLong()) {
            value = node.longValue();
        } else if (node.isFloatingPointNumber() && node.decimalValue().stripTrailingZeros().scale() <= 0
                && node.decimalValue().abs().compareTo(java.math.BigDecimal.valueOf(Long.MAX_VALUE)) < 0) {
            value = node.decimalValue().longValueExact();
        } else {
            throw ApiException.contract(path + " must be an integer");
        }
        if (value < min || value > max) {
            throw ApiException.contract(path + " must be between " + min + " and " + max);
        }
        return value;
    }

    public static double number(JsonNode node, String path, double min, double max) {
        if (node == null || !node.isNumber()) {
            throw ApiException.contract(path + " must be a number");
        }
        double value = node.doubleValue();
        if (Double.isNaN(value) || value < min || value > max) {
            throw ApiException.contract(path + " must be between " + min + " and " + max);
        }
        return value;
    }

    public static boolean isNull(JsonNode node) {
        return node != null && node.isNull();
    }

    public static JsonNode array(JsonNode node, String path, int minItems) {
        if (node == null || !node.isArray()) {
            throw ApiException.contract(path + " must be an array");
        }
        if (node.size() < minItems) {
            throw ApiException.contract(path + " must have at least " + minItems + " item(s)");
        }
        return node;
    }

    /** uniqueItems + 문자열 항목 검사. */
    public static List<String> uniqueStrings(JsonNode node, String path, int minItems, Set<String> allowedValues) {
        array(node, path, minItems);
        Set<String> seen = new HashSet<>();
        java.util.ArrayList<String> values = new java.util.ArrayList<>();
        for (int i = 0; i < node.size(); i++) {
            String item = allowedValues == null
                    ? id(node.get(i), path + "[" + i + "]")
                    : enumValue(node.get(i), path + "[" + i + "]", allowedValues);
            if (!seen.add(item)) {
                throw ApiException.contract(path + " must not contain duplicates");
            }
            values.add(item);
        }
        return values;
    }

    static int base58Size(String value) {
        BigInteger number = BigInteger.ZERO;
        BigInteger base = BigInteger.valueOf(58);
        for (char c : value.toCharArray()) {
            int digit = BASE58.indexOf(c);
            if (digit < 0) {
                return -1;
            }
            number = number.multiply(base).add(BigInteger.valueOf(digit));
        }
        int leadingZeros = 0;
        while (leadingZeros < value.length() && value.charAt(leadingZeros) == '1') {
            leadingZeros++;
        }
        return leadingZeros + (number.bitLength() + 7) / 8;
    }
}
