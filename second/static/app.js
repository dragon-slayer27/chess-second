(function () {
  "use strict";

  var SAMPLE_PGN = [
    '[Event "Club rapid"]',
    '[White "Aarav"]',
    '[Black "Opponent"]',
    '[Result "0-1"]',
    "",
    "1. e4 e5 2. Nf3 Nc6 3. Bc4 Nf6 4. Ng5 d5 5. exd5 Nxd5 6. Nxf7 Kxf7 7. Qf3+ Ke6",
    "8. Nc3 Ncb4 9. a3 Nxc2+ 10. Kd1 Nxa1 11. Nxd5 Kd6 12. d4 c6 13. Nc3 exd4",
    "14. Ne4+ Kc7 15. Bf4+ Kb6 16. Qf3 Qe7 17. Re1 Be6 18. Bxe6 Qxe6 19. Nc5 Qd5 0-1",
  ].join("\n");

  function showSource() {
    var checked = document.querySelector('input[name="source"]:checked');
    if (!checked) return;
    document.querySelectorAll(".source").forEach(function (box) {
      box.hidden = box.dataset.source !== checked.value;
    });
    var games = document.getElementById("games");
    if (games) {
      var many = checked.value === "lichess_user" || checked.value === "chesscom_user" || checked.value === "file" || checked.value === "pgn";
      games.closest("div").hidden = !many;
    }
  }

  document.querySelectorAll('input[name="source"]').forEach(function (radio) {
    radio.addEventListener("change", showSource);
  });
  showSource();

  var sample = document.getElementById("sample-pgn");
  if (sample) {
    sample.addEventListener("click", function () {
      document.getElementById("pgn_text").value = SAMPLE_PGN;
      document.getElementById("student_name").value = "Aarav";
      document.getElementById("student_color").value = "white";
    });
  }

  var engineChip = document.getElementById("status-engine");
  if (engineChip) {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (status) {
      engineChip.textContent = status.stockfish ? "Stockfish ready" : "Stockfish not found";
      engineChip.className = "chip " + (status.stockfish ? "ok" : "bad");
      var modelChip = document.getElementById("status-model");
      modelChip.textContent = status.model;
      modelChip.className = "chip " + (status.model_ok ? "ok" : "bad");
    }).catch(function () {});
  }

  var job = document.getElementById("job");
  if (job) {
    var id = job.dataset.job;
    var poll = function () {
      fetch("/api/jobs/" + id).then(function (r) { return r.json(); }).then(function (state) {
        document.getElementById("bar").style.width = Math.round(state.fraction * 100) + "%";
        document.getElementById("message").textContent = state.message;
        if (state.status === "done") {
          if (state.review_ids.length === 1) {
            window.location = "/reviews/" + state.review_ids[0];
            return;
          }
          var links = document.getElementById("links");
          links.innerHTML = "";
          state.review_ids.forEach(function (rid, i) {
            var a = document.createElement("a");
            a.href = "/reviews/" + rid;
            a.className = "button";
            a.textContent = "Game " + (i + 1);
            links.appendChild(a);
            links.appendChild(document.createTextNode(" "));
          });
          return;
        }
        if (state.status === "error") {
          document.getElementById("message").innerHTML = "";
          var p = document.createElement("strong");
          p.textContent = state.message;
          document.getElementById("message").appendChild(p);
          var back = document.createElement("a");
          back.href = "/";
          back.className = "button";
          back.textContent = "Try again";
          document.getElementById("links").appendChild(back);
          return;
        }
        setTimeout(poll, 1000);
      }).catch(function () { setTimeout(poll, 3000); });
    };
    poll();
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.querySelector(button.dataset.copy);
      navigator.clipboard.writeText(target.innerText).then(function () {
        button.textContent = "Copied!";
        setTimeout(function () { button.textContent = "Copy"; }, 2000);
      });
    });
  });
})();
