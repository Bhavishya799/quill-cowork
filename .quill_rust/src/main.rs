use clap::{Parser, Subcommand};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Command;

const SKIP_DIRS: &[&str] = &[
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "coverage", "htmlcov", ".tox", ".eggs",
];

const SKIP_EXTS: &[&str] = &[
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav", ".flac",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
];

const KEY_FILES: &[&str] = &[
    "README.md", "README.rst", "README.txt", "readme.md",
    "package.json", "pyproject.toml", "requirements.txt",
    "setup.py", "Cargo.toml", "go.mod", "pom.xml",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".env.example", "tsconfig.json",
];

const MAX_FILE_BYTES: u64 = 200_000;
const MAX_TOTAL_FILES: usize = 3000;
const MAX_TOTAL_BYTES: u64 = 30_000_000;

#[derive(Serialize, Deserialize, Clone)]
struct Record {
    path: String,
    size: u64,
    lang: String,
    lines: u32,
    content: String,
}

#[derive(Serialize, Deserialize)]
struct Meta {
    name: String,
    root: String,
    connected_at: f64,
    file_count: usize,
    total_bytes: u64,
    skipped_binary: u32,
    skipped_large: u32,
    skipped_cap: u32,
    elapsed: f64,
}

#[derive(Deserialize)]
struct Grant {
    path: String,
    #[serde(default)] read: bool,
    #[serde(default)] write: bool,
}

#[derive(Parser)]
#[command(name = "quill_core", version = "0.1.0", disable_help_subcommand = true)]
struct Cli {
    #[command(subcommand)]
    command: Cmd,
}

#[derive(Subcommand)]
enum Cmd {
    Ingest {
        #[arg(long)] root: String,
        #[arg(long, default_value = "")] name: String,
        #[arg(long)] index_root: String,
    },
    List { #[arg(long)] index_root: String },
    Meta { #[arg(long)] index_root: String, #[arg(long)] name: String },
    Disconnect { #[arg(long)] index_root: String, #[arg(long)] name: String },
    Summary { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long, default_value_t = 3500)] max_chars: usize },
    Tree { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long, default_value_t = 400)] max_lines: usize },
    Search { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long)] query: String, #[arg(long, default_value_t = 15)] limit: usize },
    Grep { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long)] pattern: String, #[arg(long, default_value_t = 40)] limit: usize },
    Read { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long)] path: String, #[arg(long, default_value_t = 8000)] max_chars: usize },
    ReadAll { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long, default_value_t = 200000)] max_chars: usize },
    Symbols { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long, default_value = "all")] kind: String, #[arg(long, default_value_t = 400)] limit: usize },
    FindSym { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long)] symbol: String },
    Imports { #[arg(long)] index_root: String, #[arg(long)] name: String, #[arg(long)] file: String, #[arg(long, default_value = "out")] direction: String },
    Write { #[arg(long)] index_root: String },
    Patch { #[arg(long)] index_root: String },
    FsList { #[arg(long)] workspace: String, #[arg(long, default_value = ".")] path: String, #[arg(long, default_value = "[]")] grants: String },
    FsRead { #[arg(long)] workspace: String, #[arg(long)] path: String, #[arg(long, default_value = "[]")] grants: String },
    FsWrite { #[arg(long)] workspace: String, #[arg(long, default_value = "[]")] grants: String },
    FsSearch { #[arg(long)] workspace: String, #[arg(long, default_value = ".")] path: String, #[arg(long)] pattern: String, #[arg(long, default_value = "[]")] grants: String },
    GitStatus { #[arg(long)] root: String },
    GitCommit { #[arg(long)] root: String, #[arg(long)] message: String },
    GitPush { #[arg(long)] root: String, #[arg(long, default_value = "origin")] remote: String, #[arg(long, default_value = "")] branch: String, #[arg(long, default_value = "")] token: String },
    Now { #[arg(long, default_value = "local")] tz: String },
}

fn sanitize(name: &str) -> String {
    let filtered: String = name.chars()
        .filter(|c| c.is_alphanumeric() || *c == '-' || *c == '_' || *c == '.')
        .collect();
    filtered.trim_matches(|c| c == '-' || c == '_').to_string()
}

fn lang_for(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()).map(|s| s.to_lowercase()).as_deref() {
        Some("py") => "python",
        Some("js") => "javascript",
        Some("ts") => "typescript",
        Some("jsx") => "jsx",
        Some("tsx") => "tsx",
        Some("java") => "java",
        Some("go") => "go",
        Some("rs") => "rust",
        Some("rb") => "ruby",
        Some("php") => "php",
        Some("c") => "c",
        Some("cpp") => "cpp",
        Some("h") => "c",
        Some("hpp") => "cpp",
        Some("cs") => "csharp",
        Some("kt") => "kotlin",
        Some("swift") => "swift",
        Some("html") => "html",
        Some("css") => "css",
        Some("json") => "json",
        Some("yaml") | Some("yml") => "yaml",
        Some("toml") => "toml",
        Some("md") => "markdown",
        Some("rst") => "rst",
        Some("txt") => "text",
        Some("sh") | Some("bash") => "shell",
        Some("ps1") => "powershell",
        Some("sql") => "sql",
        _ => "",
    }
}

fn is_binary(path: &Path) -> bool {
    let data = match fs::read(path) {
        Ok(d) => d,
        Err(_) => return true,
    };
    if data.is_empty() {
        return false;
    }
    if data.contains(&0) {
        return true;
    }
    let sample = &data[..data.len().min(8000)];
    let printable = sample.iter().filter(|b| {
        let c = **b;
        (c >= 32 && c < 127) || c == 9 || c == 10 || c == 13
    }).count();
    (printable as f64 / sample.len() as f64) < 0.85
}

fn walk(root: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    for entry in walkdir::WalkDir::new(root).into_iter().filter_entry(|e| {
        let name = e.file_name().to_string_lossy().to_string();
        if e.file_type().is_dir() {
            if name.starts_with('.') {
                return false;
            }
            if SKIP_DIRS.contains(&name.as_str()) {
                return false;
            }
        }
        true
    }) {
        let e = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        if !e.file_type().is_file() {
            continue;
        }
        let name = e.file_name().to_string_lossy().to_string();
        if name == ".DS_Store" || name == "Thumbs.db" {
            continue;
        }
        if name.ends_with(".min.js") || name.ends_with(".min.css") {
            continue;
        }
        if let Some(ext) = e.path().extension().and_then(|s| s.to_str()) {
            let dotted = format!(".{}", ext.to_lowercase());
            if SKIP_EXTS.contains(&dotted.as_str()) {
                continue;
            }
        }
        out.push(e.path().to_path_buf());
    }
    out
}

fn read_stdin_json() -> serde_json::Value {
    let mut s = String::new();
    let _ = std::io::stdin().read_to_string(&mut s);
    serde_json::from_str(&s).unwrap_or(serde_json::Value::Null)
}

fn parse_grants(raw: &str) -> Vec<Grant> {
    serde_json::from_str(raw).unwrap_or_default()
}

fn clamp_chars(s: &str, max_chars: usize) -> String {
    s.chars().take(max_chars).collect()
}

fn index_path(index_root: &Path, name: &str) -> PathBuf {
    index_root.join(sanitize(name))
}

fn read_records(idx: &Path) -> Vec<Record> {
    let f = idx.join("files.jsonl");
    let text = match fs::read_to_string(&f) {
        Ok(t) => t,
        Err(_) => return Vec::new(),
    };
    text.lines()
        .filter_map(|l| serde_json::from_str::<Record>(l).ok())
        .collect()
}

fn write_records(idx: &Path, records: &[Record]) -> std::io::Result<()> {
    let f = idx.join("files.jsonl");
    let mut out = String::new();
    for r in records {
        if let Ok(line) = serde_json::to_string(r) {
            out.push_str(&line);
            out.push('\n');
        }
    }
    fs::write(f, out)
}

fn cmd_ingest(root: &str, name: &str, index_root: &str) -> Result<(), Box<dyn std::error::Error>> {
    let root_path = Path::new(root).canonicalize()
        .map_err(|e| format!("not a directory: {} ({})", root, e))?;
    if !root_path.is_dir() {
        return Err(format!("not a directory: {}", root_path.display()).into());
    }
    let idx_name = if name.is_empty() {
        sanitize(root_path.file_name().and_then(|s| s.to_str()).unwrap_or("codebase"))
    } else {
        sanitize(name)
    };
    if idx_name.is_empty() {
        return Err("could not derive a valid codebase name".into());
    }
    let idx_dir = index_path(Path::new(index_root), &idx_name);
    if idx_dir.exists() {
        fs::remove_dir_all(&idx_dir)?;
    }
    fs::create_dir_all(&idx_dir)?;

    let started = std::time::Instant::now();
    let mut records: Vec<Record> = Vec::new();
    let mut total_bytes: u64 = 0;
    let mut skipped_binary: u32 = 0;
    let mut skipped_large: u32 = 0;
    let mut skipped_cap: u32 = 0;

    for p in walk(&root_path) {
        if records.len() >= MAX_TOTAL_FILES {
            skipped_cap += 1;
            continue;
        }
        let size = match fs::metadata(&p) {
            Ok(m) => m.len(),
            Err(_) => continue,
        };
        if size > MAX_FILE_BYTES {
            skipped_large += 1;
            continue;
        }
        if total_bytes + size > MAX_TOTAL_BYTES {
            skipped_cap += 1;
            continue;
        }
        if is_binary(&p) {
            skipped_binary += 1;
            continue;
        }
        let content = match fs::read_to_string(&p) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let rel = match p.strip_prefix(&root_path) {
            Ok(r) => r.to_string_lossy().replace('\\', "/"),
            Err(_) => continue,
        };
        let lines = content.bytes().filter(|b| *b == b'\n').count() as u32 + 1;
        records.push(Record {
            path: rel,
            size,
            lang: lang_for(&p).to_string(),
            lines,
            content,
        });
        total_bytes += size;
    }

    write_records(&idx_dir, &records)?;

    let mut tree_sorted: Vec<String> = records.iter().map(|r| r.path.clone()).collect();
    tree_sorted.sort();
    fs::write(idx_dir.join("tree.txt"), tree_sorted.join("\n"))?;

    let summary = build_summary(&idx_name, &root_path, &records, skipped_binary, skipped_large, skipped_cap, total_bytes);
    fs::write(idx_dir.join("summary.md"), &summary)?;

    let meta = Meta {
        name: idx_name.clone(),
        root: root_path.to_string_lossy().to_string(),
        connected_at: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0),
        file_count: records.len(),
        total_bytes,
        skipped_binary,
        skipped_large,
        skipped_cap,
        elapsed: started.elapsed().as_secs_f64(),
    };
    fs::write(idx_dir.join("meta.json"), serde_json::to_string_pretty(&meta)?)?;
    println!("{}", serde_json::to_string(&meta)?);
    Ok(())
}

fn build_summary(name: &str, root: &Path, records: &[Record], skipped_binary: u32, skipped_large: u32, skipped_cap: u32, total_bytes: u64) -> String {
    let mut lines = Vec::new();
    lines.push(format!("# Codebase: {}", name));
    lines.push(format!("Root: {}", root.display()));
    lines.push(format!("Indexed files: {}", records.len()));
    lines.push(format!("Total bytes: {}", total_bytes));
    if skipped_binary > 0 { lines.push(format!("Skipped binary: {}", skipped_binary)); }
    if skipped_large > 0 { lines.push(format!("Skipped >200KB: {}", skipped_large)); }
    if skipped_cap > 0 { lines.push(format!("Skipped (cap): {}", skipped_cap)); }

    let mut langs: HashMap<String, u32> = HashMap::new();
    for r in records {
        let k = if r.lang.is_empty() { "other".to_string() } else { r.lang.clone() };
        *langs.entry(k).or_insert(0) += 1;
    }
    let mut lang_vec: Vec<(String, u32)> = langs.into_iter().collect();
    lang_vec.sort_by(|a, b| b.1.cmp(&a.1));
    lines.push(String::new());
    lines.push("Languages:".to_string());
    for (lang, count) in lang_vec.iter().take(8) {
        lines.push(format!("- {}: {}", lang, count));
    }

    lines.push(String::new());
    lines.push(format!("File tree (first 100 of {}):", records.len()));
    let mut sorted: Vec<&Record> = records.iter().collect();
    sorted.sort_by(|a, b| a.path.cmp(&b.path));
    for r in sorted.iter().take(100) {
        lines.push(format!("- {}", r.path));
    }
    if records.len() > 100 {
        lines.push(format!("… ({} more, use codebase_tree to see all)", records.len() - 100));
    }

    let mut excerpts = Vec::new();
    for key in KEY_FILES {
        for r in records {
            let rp = r.path.to_lowercase();
            let kl = key.to_lowercase();
            if rp == kl || rp.ends_with(&format!("/{}", kl)) {
                let excerpt: String = r.content.chars().take(1200).collect();
                excerpts.push(format!("### {}\n```\n{}\n```", r.path, excerpt));
                break;
            }
        }
    }
    if !excerpts.is_empty() {
        lines.push(String::new());
        lines.push("Key files:".to_string());
        lines.push(excerpts.join("\n\n"));
    }

    let text = lines.join("\n");
    if text.chars().count() > 3500 {
        return format!("{}\n… [truncated]", clamp_chars(&text, 3500));
    }
    text
}

fn cmd_list(index_root: &str) -> Result<(), Box<dyn std::error::Error>> {
    let root = Path::new(index_root);
    let mut out: Vec<Meta> = Vec::new();
    if root.exists() {
        let mut entries: Vec<PathBuf> = fs::read_dir(root)?
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.is_dir() && p.join("meta.json").exists())
            .collect();
        entries.sort();
        for d in entries {
            if let Ok(t) = fs::read_to_string(d.join("meta.json")) {
                if let Ok(m) = serde_json::from_str::<Meta>(&t) {
                    out.push(m);
                }
            }
        }
    }
    println!("{}", serde_json::to_string(&out)?);
    Ok(())
}

fn cmd_meta(index_root: &str, name: &str) -> Result<(), Box<dyn std::error::Error>> {
    let f = index_path(Path::new(index_root), name).join("meta.json");
    let t = fs::read_to_string(f)?;
    let m: Meta = serde_json::from_str(&t)?;
    println!("{}", serde_json::to_string(&m)?);
    Ok(())
}

fn cmd_disconnect(index_root: &str, name: &str) -> Result<(), Box<dyn std::error::Error>> {
    let d = index_path(Path::new(index_root), name);
    if d.exists() {
        fs::remove_dir_all(&d)?;
        println!("{}", serde_json::json!({"ok": true}));
    } else {
        println!("{}", serde_json::json!({"ok": false}));
    }
    Ok(())
}

fn cmd_summary(index_root: &str, name: &str, max_chars: usize) -> Result<(), Box<dyn std::error::Error>> {
    let f = index_path(Path::new(index_root), name).join("summary.md");
    match fs::read_to_string(f) {
        Ok(s) => print!("{}", clamp_chars(&s, max_chars)),
        Err(_) => print!("no index for '{}'", name),
    }
    Ok(())
}

fn cmd_tree(index_root: &str, name: &str, max_lines: usize) -> Result<(), Box<dyn std::error::Error>> {
    let f = index_path(Path::new(index_root), name).join("tree.txt");
    match fs::read_to_string(f) {
        Ok(s) => {
            let lines: Vec<&str> = s.lines().collect();
            if lines.len() > max_lines {
                print!("{}", lines[..max_lines].join("\n"));
                print!("\n… ({} more)", lines.len() - max_lines);
            } else {
                print!("{}", s);
            }
        }
        Err(_) => print!("no index for '{}'", name),
    }
    Ok(())
}

fn snippet_around(content: &str, term: &str, before: usize, after: usize) -> String {
    let lower = content.to_lowercase();
    if let Some(pos) = lower.find(term) {
        let start = pos.saturating_sub(before);
        let end = (pos + term.len() + after).min(content.len());
        let mut s = content[start..end].replace('\n', " ");
        if start > 0 { s = format!("…{}", s); }
        if end < content.len() { s = format!("{}…", s); }
        s
    } else {
        String::new()
    }
}

fn cmd_search(index_root: &str, name: &str, query: &str, limit: usize) -> Result<(), Box<dyn std::error::Error>> {
    let idx = index_path(Path::new(index_root), name);
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    let q = query.to_lowercase().trim().to_string();
    if q.is_empty() {
        println!("empty query");
        return Ok(());
    }
    let terms: Vec<&str> = q.split_whitespace().filter(|t| t.chars().count() >= 2).collect();

    let mut scored: Vec<(u32, String, Vec<String>)> = Vec::new();
    for r in &records {
        let cl = r.content.to_lowercase();
        let pl = r.path.to_lowercase();
        let mut score: u32 = 0;
        let mut hits: Vec<String> = Vec::new();
        for term in &terms {
            if pl.contains(term) {
                score += 10;
            }
            let count = cl.matches(term).count() as u32;
            if count > 0 {
                score += count.min(5);
                hits.push(snippet_around(&r.content, term, 60, 140));
            }
        }
        if score > 0 {
            scored.push((score, r.path.clone(), hits.into_iter().take(2).collect()));
        }
    }
    if scored.is_empty() {
        println!("no matches for '{}'", query);
        return Ok(());
    }
    scored.sort_by(|a, b| b.0.cmp(&a.0));
    let mut out = String::new();
    for (i, (score, path, hits)) in scored.iter().take(limit).enumerate() {
        if i > 0 { out.push('\n'); }
        out.push_str(&format!("[{}] {}", score, path));
        for h in hits {
            out.push_str(&format!("\n    {}", h));
        }
    }
    print!("{}", out);
    Ok(())
}

fn cmd_grep(index_root: &str, name: &str, pattern: &str, limit: usize) -> Result<(), Box<dyn std::error::Error>> {
    if pattern.chars().count() > 100 {
        println!("refused: regex pattern over 100 characters");
        return Ok(());
    }
    let rx = match regex::RegexBuilder::new(pattern).case_insensitive(true).build() {
        Ok(r) => r,
        Err(e) => {
            println!("bad regex: {}", e);
            return Ok(());
        }
    };
    let idx = index_path(Path::new(index_root), name);
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    let mut out: Vec<String> = Vec::new();
    'outer: for r in &records {
        for (i, line) in r.content.split('\n').enumerate() {
            let trimmed = if line.chars().count() > 2000 {
                clamp_chars(line, 2000)
            } else {
                line.to_string()
            };
            if rx.is_match(&trimmed) {
                let content: String = trimmed.trim().chars().take(140).collect();
                out.push(format!("{}:{}: {}", r.path, i + 1, content));
                if out.len() >= limit {
                    break 'outer;
                }
            }
        }
    }
    if out.is_empty() {
        println!("no matches for /{}/", pattern);
    } else {
        print!("{}", out.join("\n"));
    }
    Ok(())
}

fn cmd_read(index_root: &str, name: &str, path: &str, max_chars: usize) -> Result<(), Box<dyn std::error::Error>> {
    let idx = index_path(Path::new(index_root), name);
    let want = path.trim().trim_start_matches(['/', '\\']).replace('\\', "/");
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    for r in &records {
        if r.path == want {
            if r.content.chars().count() > max_chars {
                print!("{}\n… (truncated, {} chars total)", clamp_chars(&r.content, max_chars), r.content.chars().count());
            } else {
                print!("{}", r.content);
            }
            return Ok(());
        }
    }
    let meta_f = idx.join("meta.json");
    if let Ok(t) = fs::read_to_string(&meta_f) {
        if let Ok(m) = serde_json::from_str::<Meta>(&t) {
            let disk = Path::new(&m.root).join(&want);
            if disk.is_file() {
                if let Ok(c) = fs::read_to_string(&disk) {
                    print!("{}", clamp_chars(&c, max_chars));
                    return Ok(());
                }
            }
        }
    }
    println!("file not found in index: {}", path);
    Ok(())
}

fn cmd_readall(index_root: &str, name: &str, max_chars: usize) -> Result<(), Box<dyn std::error::Error>> {
    let idx = index_path(Path::new(index_root), name);
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    let mut out = String::new();
    let mut total: usize = 0;
    for r in &records {
        let header = format!("\n===== {} =====\n", r.path);
        if total + header.len() + r.content.len() > max_chars {
            out.push_str(&header);
            out.push_str("[truncated]");
            break;
        }
        out.push_str(&header);
        out.push_str(&r.content);
        total += header.len() + r.content.len();
    }
    print!("{}", out);
    Ok(())
}

#[derive(Debug)]
struct Symbol {
    name: String,
    kind: &'static str,
    line: u32,
}

fn extract_symbols(path: &str, content: &str) -> Vec<Symbol> {
    let mut out = Vec::new();
    let is_py = path.ends_with(".py");
    let is_js = path.ends_with(".js") || path.ends_with(".ts") || path.ends_with(".jsx")
        || path.ends_with(".tsx") || path.ends_with(".mjs") || path.ends_with(".cjs");
    if !is_py && !is_js {
        return out;
    }
    let py_fn = Regex::new(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)").ok();
    let py_cls = Regex::new(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)").ok();
    let js_fn = Regex::new(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)").ok();
    let js_arrow = Regex::new(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(").ok();
    let js_cls = Regex::new(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)").ok();
    let js_iface = Regex::new(r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)").ok();
    let js_type = Regex::new(r"^\s*(?:export\s+)?type\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=").ok();

    for (i, line) in content.split('\n').enumerate() {
        let ln = i as u32 + 1;
        if is_py {
            if let Some(rx) = &py_fn { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "function", line: ln }); continue; } }
            if let Some(rx) = &py_cls { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "class", line: ln }); continue; } }
        }
        if is_js {
            if let Some(rx) = &js_fn { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "function", line: ln }); continue; } }
            if let Some(rx) = &js_arrow { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "function", line: ln }); continue; } }
            if let Some(rx) = &js_cls { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "class", line: ln }); continue; } }
            if let Some(rx) = &js_iface { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "interface", line: ln }); continue; } }
            if let Some(rx) = &js_type { if let Some(c) = rx.captures(line) { out.push(Symbol { name: c[1].to_string(), kind: "type", line: ln }); continue; } }
        }
    }
    out
}

fn cmd_symbols(index_root: &str, name: &str, kind: &str, limit: usize) -> Result<(), Box<dyn std::error::Error>> {
    let idx = index_path(Path::new(index_root), name);
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    let want = kind.to_lowercase();
    let mut rows: Vec<(String, &'static str, String, u32)> = Vec::new();
    for r in &records {
        for s in extract_symbols(&r.path, &r.content) {
            if want != "all" && s.kind != want { continue; }
            rows.push((r.path.clone(), s.kind, s.name, s.line));
        }
    }
    if rows.is_empty() {
        println!("no symbols found in '{}'", name);
        return Ok(());
    }
    rows.sort_by(|a, b| a.0.cmp(&b.0).then(a.3.cmp(&b.3)));
    let mut out: Vec<String> = Vec::new();
    for (p, k, n, l) in rows.iter().take(limit) {
        out.push(format!("{}:{}  {}  {}", p, l, k, n));
    }
    if rows.len() > limit {
        out.push(format!("… ({} more)", rows.len() - limit));
    }
    print!("{}", out.join("\n"));
    Ok(())
}

fn cmd_findsym(index_root: &str, name: &str, symbol: &str) -> Result<(), Box<dyn std::error::Error>> {
    let idx = index_path(Path::new(index_root), name);
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    let sym = symbol.trim();
    if sym.is_empty() {
        println!("empty symbol");
        return Ok(());
    }
    let src_rx = Regex::new(&format!(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|const|let|var|def)\s+{}\b",
        regex::escape(sym)
    )).ok();
    let mut matches: Vec<String> = Vec::new();
    for r in &records {
        let mut found = false;
        for s in extract_symbols(&r.path, &r.content) {
            if s.name == sym {
                matches.push(format!("{}:{}  {}", r.path, s.line, s.kind));
                found = true;
                break;
            }
        }
        if !found {
            if let Some(rx) = &src_rx {
                for (i, line) in r.content.split('\n').enumerate() {
                    if rx.is_match(line) {
                        matches.push(format!("{}:{}  (source)", r.path, i + 1));
                        break;
                    }
                }
            }
        }
    }
    if matches.is_empty() {
        println!("symbol not found: {}", sym);
    } else {
        let take = matches.len().min(20);
        print!("{}", matches[..take].join("\n"));
    }
    Ok(())
}

fn imports_of(path: &str, content: &str) -> Vec<String> {
    let mut mods = Vec::new();
    let is_py = path.ends_with(".py");
    let is_js = path.ends_with(".js") || path.ends_with(".ts") || path.ends_with(".jsx")
        || path.ends_with(".tsx") || path.ends_with(".mjs") || path.ends_with(".cjs");
    if is_py {
        let from_rx = Regex::new(r"(?m)^\s*from\s+([\w\.]+)\s+import\s+").ok();
        let plain_rx = Regex::new(r"(?m)^\s*import\s+([\w\.]+)").ok();
        if let Some(rx) = from_rx { for c in rx.captures_iter(content) { mods.push(c[1].to_string()); } }
        if let Some(rx) = plain_rx { for c in rx.captures_iter(content) { mods.push(c[1].to_string()); } }
    } else if is_js {
        let rx = Regex::new(r#"(?:^|\n)\s*(?:import\s+(?:[^'"]+\s+from\s+)?|require\s*\(\s*)['"]([^'"]+)['"]"#).ok();
        if let Some(rx) = rx { for c in rx.captures_iter(content) { mods.push(c[1].to_string()); } }
    }
    mods
}

fn cmd_imports(index_root: &str, name: &str, file: &str, direction: &str) -> Result<(), Box<dyn std::error::Error>> {
    let idx = index_path(Path::new(index_root), name);
    let records = read_records(&idx);
    if records.is_empty() {
        println!("no index for '{}'", name);
        return Ok(());
    }
    let want = file.trim().trim_start_matches(['/', '\\']).replace('\\', "/");
    let dir = direction.to_lowercase();

    if dir == "out" {
        for r in &records {
            if r.path == want {
                let mods = imports_of(&r.path, &r.content);
                if mods.is_empty() {
                    println!("{} imports nothing", want);
                } else {
                    print!("{}", mods.iter().map(|m| format!("- {}", m)).collect::<Vec<_>>().join("\n"));
                }
                return Ok(());
            }
        }
        println!("file not found in index: {}", file);
        return Ok(());
    }

    if dir == "in" {
        let base = Path::new(&want).file_stem().and_then(|s| s.to_str()).unwrap_or("").to_string();
        let dotted = want.replace('/', ".").replace('\\', ".");
        let mut hit: Vec<String> = Vec::new();
        for r in &records {
            if r.path == want {
                continue;
            }
            for m in imports_of(&r.path, &r.content) {
                let tail = m.split(|c| c == '.' || c == '/').last().unwrap_or("");
                if tail == base || m == dotted {
                    hit.push(format!("{}  → {}", r.path, m));
                    break;
                }
            }
        }
        if hit.is_empty() {
            println!("nothing imports {}", want);
        } else {
            let take = hit.len().min(50);
            print!("{}", hit[..take].join("\n"));
        }
        return Ok(());
    }

    println!("unknown direction: {}", direction);
    Ok(())
}

fn update_index_record(idx: &Path, rel: &str, content: &str) -> std::io::Result<()> {
    let mut records = read_records(idx);
    let mut found = false;
    for r in records.iter_mut() {
        if r.path == rel {
            r.content = content.to_string();
            r.size = content.len() as u64;
            r.lines = content.bytes().filter(|b| *b == b'\n').count() as u32 + 1;
            found = true;
        }
    }
    if !found {
        records.push(Record {
            path: rel.to_string(),
            size: content.len() as u64,
            lang: lang_for(Path::new(rel)).to_string(),
            lines: content.bytes().filter(|b| *b == b'\n').count() as u32 + 1,
            content: content.to_string(),
        });
    }
    write_records(idx, &records)
}

fn load_meta(idx: &Path) -> Option<Meta> {
    fs::read_to_string(idx.join("meta.json")).ok()
        .and_then(|t| serde_json::from_str(&t).ok())
}

fn cmd_write(index_root: &str) -> Result<(), Box<dyn std::error::Error>> {
    let payload = read_stdin_json();
    let name = payload.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let rel = payload.get("path").and_then(|v| v.as_str()).unwrap_or("");
    let content = payload.get("content").and_then(|v| v.as_str()).unwrap_or("");
    let idx = index_path(Path::new(index_root), name);
    let meta = match load_meta(&idx) {
        Some(m) => m,
        None => { println!("no codebase named '{}'", name); return Ok(()); }
    };
    let root = Path::new(&meta.root).canonicalize()?;
    let trimmed = rel.trim_start_matches(['/', '\\']);
    let target = root.join(trimmed);
    let target_resolved = target.canonicalize().unwrap_or(target.clone());
    if !target_resolved.starts_with(&root) {
        println!("refused: {} escapes codebase root", rel);
        return Ok(());
    }
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&target, content)?;
    let rel_slash = trimmed.replace('\\', "/");
    update_index_record(&idx, &rel_slash, content)?;
    println!("wrote {} chars to {}", content.len(), rel_slash);
    Ok(())
}

fn cmd_patch(index_root: &str) -> Result<(), Box<dyn std::error::Error>> {
    let payload = read_stdin_json();
    let name = payload.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let rel = payload.get("path").and_then(|v| v.as_str()).unwrap_or("");
    let find = payload.get("find").and_then(|v| v.as_str()).unwrap_or("");
    let replace = payload.get("replace").and_then(|v| v.as_str()).unwrap_or("");
    let count = payload.get("count").and_then(|v| v.as_u64()).unwrap_or(1) as usize;
    let idx = index_path(Path::new(index_root), name);
    let meta = match load_meta(&idx) {
        Some(m) => m,
        None => { println!("no codebase named '{}'", name); return Ok(()); }
    };
    let root = Path::new(&meta.root).canonicalize()?;
    let trimmed = rel.trim_start_matches(['/', '\\']);
    let target = root.join(trimmed);
    let target_resolved = target.canonicalize().unwrap_or(target.clone());
    if !target_resolved.starts_with(&root) {
        println!("refused: {} escapes codebase root", rel);
        return Ok(());
    }
    if !target.is_file() {
        println!("not found: {}", trimmed);
        return Ok(());
    }
    let original = fs::read_to_string(&target)?;
    if find.is_empty() {
        println!("find string is empty");
        return Ok(());
    }
    if !original.contains(find) {
        println!("find string not present in {}", trimmed);
        return Ok(());
    }
    let occurrences = original.matches(find).count();
    if occurrences > 1 && count == 1 {
        println!("find string appears {} times in {}; pass count={} to replace all, or use a more specific find", occurrences, trimmed, occurrences);
        return Ok(());
    }
    let replace_n = if count == 0 || count > occurrences { occurrences } else { count };
    let mut new_content = String::with_capacity(original.len());
    let mut last = 0;
    let mut done = 0;
    for (pos, mat) in original.match_indices(find) {
        if done >= replace_n { break; }
        new_content.push_str(&original[last..pos]);
        new_content.push_str(replace);
        last = pos + mat.len();
        done += 1;
    }
    new_content.push_str(&original[last..]);
    if new_content == original {
        println!("no change made");
        return Ok(());
    }
    fs::write(&target, &new_content)?;
    let rel_slash = trimmed.replace('\\', "/");
    update_index_record(&idx, &rel_slash, &new_content)?;
    println!("patched {}: replaced {} occurrence(s)", rel_slash, replace_n);
    Ok(())
}

fn resolve_fs(workspace: &Path, raw: &str, grants: &[Grant], write: bool) -> Result<PathBuf, String> {
    let mut r = raw.trim();
    let lower = r.to_lowercase();
    if lower.starts_with("/workspace/") {
        r = &r["/workspace/".len()..];
    } else if lower.starts_with("\\workspace\\") {
        r = &r["\\workspace\\".len()..];
    }
    let root_aliases = ["", ".", "/", "workspace", "/workspace", "\\workspace",
        "./workspace", ".\\workspace", "the workspace", "the workspace root",
        "workspace root", "workspace/"];
    if root_aliases.iter().any(|a| *a == r || *a == r.to_lowercase()) {
        return Ok(workspace.to_path_buf());
    }
    let p = Path::new(r);
    let p = if p.is_absolute() { p.to_path_buf() } else { workspace.join(r) };
    match p.canonicalize() {
        Ok(cp) => {
            if cp.starts_with(workspace) {
                return Ok(cp);
            }
            for g in grants {
                let g_path = Path::new(&g.path);
                if cp.starts_with(g_path) {
                    if write && !g.write {
                        return Err(format!("no write permission for granted folder: {}", g.path));
                    }
                    if !write && !g.read {
                        return Err(format!("no read permission for granted folder: {}", g.path));
                    }
                    return Ok(cp);
                }
            }
            Err(format!("path outside workspace and not in any granted folder: {} (workspace is {})", r, workspace.display()))
        }
        Err(_) => {
            if write {
                if let Some(parent) = p.parent() {
                    if let Ok(pp) = parent.canonicalize() {
                        if pp.starts_with(workspace) {
                            return Ok(p);
                        }
                        for g in grants {
                            let g_path = Path::new(&g.path);
                            if pp.starts_with(g_path) && g.write {
                                return Ok(p);
                            }
                        }
                    }
                }
                Err(format!("path outside workspace and not in any granted folder: {} (workspace is {})", r, workspace.display()))
            } else {
                Err(format!("path does not exist: {}", r))
            }
        }
    }
}

fn cmd_fs_list(workspace: &str, path: &str, grants_raw: &str) -> Result<(), Box<dyn std::error::Error>> {
    let ws = Path::new(workspace).canonicalize()?;
    let grants = parse_grants(grants_raw);
    let p = match resolve_fs(&ws, path, &grants, false) {
        Ok(p) => p,
        Err(e) => { println!("cannot list '{}': {}. Use '.' to list the workspace root.", path, e); return Ok(()); }
    };
    if !p.exists() {
        println!("path does not exist: {} (resolved to {})", path, p.display());
        return Ok(());
    }
    if !p.is_dir() {
        println!("not a directory: {} (resolved to {})", path, p.display());
        return Ok(());
    }
    let mut entries: Vec<String> = fs::read_dir(&p)?
        .filter_map(|e| e.ok())
        .map(|e| {
            let n = e.file_name().to_string_lossy().to_string();
            let tag = if e.path().is_dir() { "[DIR]" } else { "[FILE]" };
            format!("{} {}", tag, n)
        })
        .collect();
    entries.sort();
    if entries.is_empty() {
        print!("(empty)");
    } else {
        print!("{}", entries.join("\n"));
    }
    Ok(())
}

fn cmd_fs_read(workspace: &str, path: &str, grants_raw: &str) -> Result<(), Box<dyn std::error::Error>> {
    let ws = Path::new(workspace).canonicalize()?;
    let grants = parse_grants(grants_raw);
    let p = match resolve_fs(&ws, path, &grants, false) {
        Ok(p) => p,
        Err(e) => { println!("cannot read '{}': {}", path, e); return Ok(()); }
    };
    if !p.exists() {
        println!("file does not exist: {} (resolved to {})", path, p.display());
        return Ok(());
    }
    if !p.is_file() {
        println!("not a file: {} (resolved to {})", path, p.display());
        return Ok(());
    }
    let bytes = fs::read(&p)?;
    let text = String::from_utf8_lossy(&bytes).to_string();
    print!("{}", clamp_chars(&text, 8000));
    Ok(())
}

fn cmd_fs_write(workspace: &str, grants_raw: &str) -> Result<(), Box<dyn std::error::Error>> {
    let payload = read_stdin_json();
    let path = payload.get("path").and_then(|v| v.as_str()).unwrap_or("");
    let content = payload.get("content").and_then(|v| v.as_str()).unwrap_or("");
    let ws = Path::new(workspace).canonicalize()?;
    let grants = parse_grants(grants_raw);
    let p = match resolve_fs(&ws, path, &grants, true) {
        Ok(p) => p,
        Err(e) => { println!("cannot write '{}': {}", path, e); return Ok(()); }
    };
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&p, content)?;
    println!("wrote {} chars to {}", content.len(), path);
    Ok(())
}

fn cmd_fs_search(workspace: &str, path: &str, pattern: &str, grants_raw: &str) -> Result<(), Box<dyn std::error::Error>> {
    let ws = Path::new(workspace).canonicalize()?;
    let grants = parse_grants(grants_raw);
    let base = match resolve_fs(&ws, path, &grants, false) {
        Ok(p) => p,
        Err(e) => { println!("cannot search '{}': {}", path, e); return Ok(()); }
    };
    if !base.is_dir() {
        println!("not a directory: {} (resolved to {})", path, base.display());
        return Ok(());
    }
    let mut matches: Vec<String> = Vec::new();
    for entry in walkdir::WalkDir::new(&base).into_iter().filter_entry(|e| {
        let name = e.file_name().to_string_lossy().to_string();
        if e.file_type().is_dir() {
            if name.starts_with('.') { return false; }
            if SKIP_DIRS.contains(&name.as_str()) { return false; }
        }
        true
    }) {
        let e = match entry { Ok(e) => e, Err(_) => continue };
        if !e.file_type().is_file() { continue; }
        let fname = e.file_name().to_string_lossy().to_string();
        if fnmatch(&fname, pattern) {
            let rel = e.path().strip_prefix(&base).unwrap_or(e.path());
            matches.push(rel.to_string_lossy().replace('\\', "/"));
            if matches.len() >= 50 { break; }
        }
    }
    if matches.is_empty() {
        println!("no files match '{}'", pattern);
    } else {
        print!("{}", matches.join("\n"));
    }
    Ok(())
}

fn fnmatch(name: &str, pattern: &str) -> bool {
    let mut rx = String::from("^");
    for c in pattern.chars() {
        match c {
            '*' => rx.push_str(".*"),
            '?' => rx.push('.'),
            '.' => rx.push_str("\\."),
            _ => rx.push(c),
        }
    }
    rx.push('$');
    Regex::new(&rx).map(|r| r.is_match(name)).unwrap_or(false)
}

fn git_status(root: &str) -> Result<(), Box<dyn std::error::Error>> {
    let root = Path::new(root);
    if !root.join(".git").exists() {
        println!("not a git repository");
        return Ok(());
    }
    let out = Command::new("git").args(["status", "--short", "--branch"]).current_dir(root).output();
    match out {
        Ok(o) => {
            let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
            if s.is_empty() { println!("(clean)"); } else { print!("{}", s); }
        }
        Err(e) => println!("git status failed: {}", e),
    }
    Ok(())
}

fn git_commit(root: &str, message: &str) -> Result<(), Box<dyn std::error::Error>> {
    let root = Path::new(root);
    if !root.join(".git").exists() {
        println!("not a git repository");
        return Ok(());
    }
    let _ = Command::new("git").args(["add", "-A"]).current_dir(root).output();
    let out = Command::new("git").args(["commit", "-m", message]).current_dir(root).output();
    match out {
        Ok(o) => {
            if !o.status.success() {
                let combined = format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr));
                println!("commit failed: {}", clamp_chars(&combined.trim().to_string(), 300));
            } else {
                print!("{}", clamp_chars(&String::from_utf8_lossy(&o.stdout).trim().to_string(), 400));
            }
        }
        Err(e) => println!("git commit failed: {}", e),
    }
    Ok(())
}

fn git_push(root: &str, remote: &str, branch: &str, token: &str) -> Result<(), Box<dyn std::error::Error>> {
    let root = Path::new(root);
    if !root.join(".git").exists() {
        println!("not a git repository");
        return Ok(());
    }
    let mut askpass_path: Option<PathBuf> = None;
    if !token.is_empty() {
        let suffix = if cfg!(windows) { "cmd" } else { "sh" };
        let p = std::env::temp_dir().join(format!("quill-askpass-{}.{}", std::process::id(), suffix));
        if cfg!(windows) {
            fs::write(&p, format!("@echo off\r\necho {}\r\n", token))?;
        } else {
            fs::write(&p, format!("#!/bin/sh\necho \"{}\"\n", token))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let mut perms = fs::metadata(&p)?.permissions();
                perms.set_mode(0o700);
                fs::set_permissions(&p, perms)?;
            }
        }
        askpass_path = Some(p);
    }

    let mut cmd = Command::new("git");
    cmd.arg("push").arg(remote);
    if !branch.is_empty() { cmd.arg(branch); }
    cmd.current_dir(root);
    if let Some(ref p) = askpass_path {
        cmd.env("GIT_ASKPASS", p);
        cmd.env("GIT_TERMINAL_PROMPT", "0");
    }
    let out = cmd.output();
    if let Some(p) = askpass_path {
        let _ = fs::remove_file(p);
    }
    match out {
        Ok(o) => {
            if !o.status.success() {
                let combined = format!("{}{}", String::from_utf8_lossy(&o.stdout), String::from_utf8_lossy(&o.stderr));
                println!("push failed: {}", clamp_chars(&combined.trim().to_string(), 400));
            } else {
                let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
                let e = String::from_utf8_lossy(&o.stderr).trim().to_string();
                let out = if !s.is_empty() { s } else if !e.is_empty() { e } else { "pushed".to_string() };
                print!("{}", clamp_chars(&out, 400));
            }
        }
        Err(e) => println!("push failed: {}", e),
    }
    Ok(())
}

fn cmd_now(tz: &str) -> Result<(), Box<dyn std::error::Error>> {
    use chrono::Local;
    let formatted = if tz == "local" {
        Local::now().format("%A, %d %B %Y, %H:%M %Z (%z)").to_string()
    } else {
        match tz.parse::<chrono_tz::Tz>() {
            Ok(t) => chrono::Utc::now().with_timezone(&t).format("%A, %d %B %Y, %H:%M %Z (%z)").to_string(),
            Err(_) => {
                println!("bad timezone '{}'", tz);
                return Ok(());
            }
        }
    };
    print!("{}", formatted);
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();
    match cli.command {
        Cmd::Ingest { root, name, index_root } => cmd_ingest(&root, &name, &index_root)?,
        Cmd::List { index_root } => cmd_list(&index_root)?,
        Cmd::Meta { index_root, name } => cmd_meta(&index_root, &name)?,
        Cmd::Disconnect { index_root, name } => cmd_disconnect(&index_root, &name)?,
        Cmd::Summary { index_root, name, max_chars } => cmd_summary(&index_root, &name, max_chars)?,
        Cmd::Tree { index_root, name, max_lines } => cmd_tree(&index_root, &name, max_lines)?,
        Cmd::Search { index_root, name, query, limit } => cmd_search(&index_root, &name, &query, limit)?,
        Cmd::Grep { index_root, name, pattern, limit } => cmd_grep(&index_root, &name, &pattern, limit)?,
        Cmd::Read { index_root, name, path, max_chars } => cmd_read(&index_root, &name, &path, max_chars)?,
        Cmd::ReadAll { index_root, name, max_chars } => cmd_readall(&index_root, &name, max_chars)?,
        Cmd::Symbols { index_root, name, kind, limit } => cmd_symbols(&index_root, &name, &kind, limit)?,
        Cmd::FindSym { index_root, name, symbol } => cmd_findsym(&index_root, &name, &symbol)?,
        Cmd::Imports { index_root, name, file, direction } => cmd_imports(&index_root, &name, &file, &direction)?,
        Cmd::Write { index_root } => cmd_write(&index_root)?,
        Cmd::Patch { index_root } => cmd_patch(&index_root)?,
        Cmd::FsList { workspace, path, grants } => cmd_fs_list(&workspace, &path, &grants)?,
        Cmd::FsRead { workspace, path, grants } => cmd_fs_read(&workspace, &path, &grants)?,
        Cmd::FsWrite { workspace, grants } => cmd_fs_write(&workspace, &grants)?,
        Cmd::FsSearch { workspace, path, pattern, grants } => cmd_fs_search(&workspace, &path, &pattern, &grants)?,
        Cmd::GitStatus { root } => git_status(&root)?,
        Cmd::GitCommit { root, message } => git_commit(&root, &message)?,
        Cmd::GitPush { root, remote, branch, token } => git_push(&root, &remote, &branch, &token)?,
        Cmd::Now { tz } => cmd_now(&tz)?,
    }
    Ok(())
}
