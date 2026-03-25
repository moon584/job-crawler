const SAMPLE_COMPANY_ID = "CXXX";
const SAMPLE_RULE_TEMPLATE = {
  company_id: "",
  company_name: "",
  provider: "config",
  list_api: {
    url: "https://example.com/api/list",
    default_params: {
      countryId: "",
      cityId: "",
      categoryId: "",
      pageIndex: 1,
      pageSize: 20,
      language: "zh-cn",
      area: "cn",
    },
  },
  detail_api: {
    url: "https://example.com/api/detail",
    default_params: {
      language: "zh-cn",
    },
  },
  throttle: {
    min_seconds: 1,
    max_seconds: 2,
    max_retries: 5,
    retry_backoff: 1.5,
    timeout: 20,
  },
  extra: {
    default_category_id: "CXXXDEFAULT",
    field_map: {
      job_url: "detail.url",
      title: "detail.title",
      description: "detail.description",
      requirement: "detail.requirement",
      salary: "detail.salary",
      bonus: "detail.bonus",
      work_experience: "detail.experience",
      education: "detail.education",
      location: "detail.city",
      publish_time: "detail.publish_time",
    },
    default_values: {
      salary: "面议",
      bonus: "NULL",
    },
    list: {
      code_field: "status.code",
      success_value: 0,
      data_path: "data",
      posts_path: "items",
      count_path: "total",
      post_id_field: "id",
      page_param: "page",
      size_param: "pageSize",
      page_size: 20,
      timestamp_param: null,
      category_param: null,
    },
    detail: {
      code_field: "status.code",
      success_value: 0,
      data_path: "data",
    },
  },
};

function autoResize(textarea) {
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function bindAutoResize() {
  const textareas = document.querySelectorAll("textarea");
  textareas.forEach((textarea) => {
    autoResize(textarea);
    textarea.addEventListener("input", () => autoResize(textarea));
  });
}

function showToast(message, variant = "info") {
  elements.toast.textContent = message;
  elements.toast.className = `toast ${variant}`;
  requestAnimationFrame(() => {
    elements.toast.classList.remove("hidden");
    setTimeout(() => elements.toast.classList.add("hidden"), 3000);
  });
}

function loadRuleIntoForm(rule) {
  const { fields } = elements;
  fields.companyId.value = rule.company_id ?? "";
  fields.companyName.value = rule.company_name ?? "";
  fields.provider.value = rule.provider ?? "";
  fields.listUrl.value = rule.list_api?.url ?? "";
  fields.detailUrl.value = rule.detail_api?.url ?? "";
  fields.defaultCategory.value = rule.extra?.default_category_id ?? "";
  fields.listParams.value = formatJson(rule.list_api?.default_params ?? {});
  fields.detailParams.value = formatJson(rule.detail_api?.default_params ?? {});
  fields.fieldMap.value = formatJson(rule.extra?.field_map ?? {});
  fields.defaultValues.value = formatJson(rule.extra?.default_values ?? {});
  fields.extraList.value = rule.extra?.list ? formatJson(rule.extra.list) : "";
  fields.extraDetail.value = rule.extra?.detail ? formatJson(rule.extra.detail) : "";
  fields.extraHeaders.value = rule.extra?.headers ? formatJson(rule.extra.headers) : "";
  fields.extraListHeaders.value = rule.extra?.list_headers ? formatJson(rule.extra.list_headers) : "";
  fields.extraDetailHeaders.value = rule.extra?.detail_headers ? formatJson(rule.extra.detail_headers) : "";
  Object.values(fields).forEach((input) => {
    if (input && input.tagName === "TEXTAREA") {
      autoResize(input);
    }
  });
  elements.validation.textContent = "";
}

function formatJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (err) {
    return "";
  }
}

function parseJsonField(text, fieldName) {
  if (!text.trim()) {
    return undefined;
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(`${fieldName} 不是合法 JSON: ${err.message}`);
  }
}

function extractForm() {
  const { fields } = elements;
  const company_id = fields.companyId.value.trim();
  if (!company_id) {
    throw new Error("company_id 不能为空");
  }
  const company_name = fields.companyName.value.trim();
  const provider = fields.provider.value.trim() || "config";
  const list_api = {
    url: fields.listUrl.value.trim(),
    default_params: parseJsonField(fields.listParams.value, "list_api.default_params") ?? {},
  };
  const detail_api = {
    url: fields.detailUrl.value.trim(),
    default_params: parseJsonField(fields.detailParams.value, "detail_api.default_params") ?? {},
  };
  const extra = {
    default_category_id: fields.defaultCategory.value.trim() || undefined,
    field_map: parseJsonField(fields.fieldMap.value, "extra.field_map") ?? {},
    default_values: parseJsonField(fields.defaultValues.value, "extra.default_values") ?? {},
  };
  const optional = [
    ["list", fields.extraList],
    ["detail", fields.extraDetail],
    ["headers", fields.extraHeaders],
    ["list_headers", fields.extraListHeaders],
    ["detail_headers", fields.extraDetailHeaders],
  ];
  optional.forEach(([key, input]) => {
    const value = parseJsonField(input.value, `extra.${key}`);
    if (value !== undefined) {
      extra[key] = value;
    }
  });
  return {
    company_id,
    company_name,
    provider,
    list_api,
    detail_api,
    extra,
  };
}

function applyFormToState() {
  if (state.activeIndex === null) {
    return;
  }
  try {
    const updated = extractForm();
    state.rules[state.activeIndex] = {
      ...state.rules[state.activeIndex],
      ...updated,
    };
    return true;
  } catch (err) {
    elements.validation.textContent = err.message;
    elements.validation.classList.add("error");
    return false;
  }
}

function renderList() {
  elements.list.innerHTML = "";
  const term = elements.search.value.trim().toLowerCase();
  state.filteredIndexes = state.rules
    .map((rule, index) => ({ rule, index }))
    .filter(({ rule }) => {
      if (!term) return true;
      return (
        (rule.company_id || "").toLowerCase().includes(term) ||
        (rule.company_name || "").toLowerCase().includes(term)
      );
    })
    .map(({ index }) => index);
  state.filteredIndexes.forEach((index) => {
    const item = document.createElement("li");
    const rule = state.rules[index];
    item.textContent = `${rule.company_id || "<未设置>"} ${rule.company_name || ""}`;
    item.dataset.index = String(index);
    if (index === state.activeIndex) {
      item.classList.add("active");
    }
    elements.list.appendChild(item);
  });
  if (!state.filteredIndexes.includes(state.activeIndex ?? -1) && state.filteredIndexes.length) {
    selectRule(state.filteredIndexes[0]);
  }
}

function selectRule(index) {
  state.activeIndex = index;
  renderList();
  loadRuleIntoForm(state.rules[index]);
}

function isSampleRule(rule) {
  return (rule?.company_id || "").toUpperCase() === SAMPLE_COMPANY_ID;
}

function cloneRule(rule) {
  return JSON.parse(JSON.stringify(rule));
}

function clearForm() {
  Object.values(elements.fields).forEach((input) => {
    if (!input) return;
    input.value = "";
    if (input.tagName === "TEXTAREA") {
      autoResize(input);
    }
  });
}

async function fetchRules() {
  const res = await fetch("/api/rules");
  if (!res.ok) {
    throw new Error("获取规则失败");
  }
  state.rules = await res.json();
  if (!Array.isArray(state.rules)) {
    throw new Error("规则文件格式异常");
  }
  const sample = state.rules.find(isSampleRule);
  state.sampleTemplate = sample ? cloneRule(sample) : cloneRule(SAMPLE_RULE_TEMPLATE);
  renderList();
  if (state.rules.length) {
    selectRule(0);
  } else {
    state.activeIndex = null;
    clearForm();
    elements.list.innerHTML = "";
  }
}

async function saveRules() {
  if (!applyFormToState()) {
    return;
  }
  const res = await fetch("/api/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.rules),
  });
  const payload = await res.json();
  if (!res.ok || !payload.success) {
    elements.validation.textContent = (payload.errors || ["未知错误"]).join("\n");
    elements.validation.classList.add("error");
    showToast("保存失败", "error");
    return;
  }
  elements.validation.textContent = "保存成功";
  elements.validation.classList.remove("error");
  showToast("保存成功", "success");
  await fetchRules();
}

function addRule() {
  const template = state.sampleTemplate ? cloneRule(state.sampleTemplate) : cloneRule(SAMPLE_RULE_TEMPLATE);
  const newRule = template;
  state.rules.unshift(newRule);
  renderList();
  selectRule(0);
}

elements.list.addEventListener("click", (event) => {
  const li = event.target.closest("li");
  if (!li || !applyFormToState()) return;
  selectRule(Number(li.dataset.index));
});

elements.search.addEventListener("input", () => {
  renderList();
});

elements.reload.addEventListener("click", async () => {
  await fetchRules();
  showToast("已重新加载", "info");
});

elements.add.addEventListener("click", () => {
  if (!applyFormToState()) return;
  addRule();
});

elements.delete.addEventListener("click", () => {
  if (state.activeIndex === null) {
    showToast("请先选择一条规则", "error");
    return;
  }
  state.rules.splice(state.activeIndex, 1);
  if (!state.rules.length) {
    state.activeIndex = null;
    clearForm();
    renderList();
    showToast("已删除当前规则", "success");
    return;
  }
  const nextIndex = Math.min(state.activeIndex, state.rules.length - 1);
  state.activeIndex = null;
  renderList();
  selectRule(nextIndex);
  showToast("已删除当前规则", "success");
});

elements.save.addEventListener("click", () => {
  saveRules().catch((err) => {
    showToast(err.message, "error");
  });
});

fetchRules().catch((err) => {
  elements.validation.textContent = err.message;
  elements.validation.classList.add("error");
});

bindAutoResize();
