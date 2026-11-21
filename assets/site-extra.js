/* Formularios estaticos: monta a mensagem e abre o WhatsApp da EletroAlta.
   (Substituir por um servico de e-mail/endpoint quando o site for ao ar.) */
(function () {
  var WHATS = "5516992077886";

  function labelOf(field) {
    var l = field.querySelector(".wpforms-field-label");
    if (!l) { l = field.querySelector("label"); }
    return l ? l.textContent.replace("*", "").trim() : "";
  }

  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form.matches || !form.matches("[data-ea-form]")) { return; }
    ev.preventDefault();
    var lines = ["Olá, EletroAlta! Segue meu contato pelo site:"];
    form.querySelectorAll(".wpforms-field").forEach(function (f) {
      var label = labelOf(f), vals = [];
      f.querySelectorAll("input, select, textarea").forEach(function (el) {
        if (el.type === "checkbox" || el.type === "radio") {
          if (el.checked) { vals.push((el.parentNode.textContent || "").trim() || "sim"); }
        } else if (el.value && el.value.trim()) {
          vals.push(el.value.trim());
        }
      });
      if (vals.length) { lines.push((label ? label + ": " : "") + vals.join(" ")); }
    });
    window.open("https://wa.me/" + WHATS + "?text=" + encodeURIComponent(lines.join("\n")), "_blank", "noopener");
  });
})();
