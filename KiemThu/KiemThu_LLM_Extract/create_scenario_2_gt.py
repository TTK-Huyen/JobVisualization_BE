import json
import os
import sys
from pathlib import Path

# Fix encoding for Windows console
sys.stdout.reconfigure(encoding='utf-8')

workspace_root = Path(r"f:\HCMUS_KH\LuanVan\JobVisualization_BE")
script_dir = workspace_root / "KiemThu" / "KiemThu_LLM_Extract"

pipeline_file = script_dir / "pipeline_jds_output.json"
db_skills_file = script_dir / "db_skills.json"
output_file = script_dir / "ground_truth_normalization.json"

def main():
    if not pipeline_file.exists():
        print(f"❌ Error: {pipeline_file.name} not found.")
        sys.exit(1)
    if not db_skills_file.exists():
        print(f"❌ Error: {db_skills_file.name} not found.")
        sys.exit(1)
        
    with open(pipeline_file, "r", encoding="utf-8") as f:
        pipe_data = json.load(f)
    with open(db_skills_file, "r", encoding="utf-8") as f:
        db_skills = json.load(f)
        
    # Map lowercase standard names to original standard names in DB
    db_map = {s["name"].lower().strip(): s["name"] for s in db_skills}
    
    # Manual overrides for skills that are valid but need standard mapping or new skill/rác classification
    manual_mappings = {
        # Standard technology mappings
        ".net": "Microsoft .NET",
        "aws": "Amazon Web Services (AWS)",
        "aws cloud": "Amazon Web Services (AWS)",
        "azure": "Microsoft Azure",
        "angular": "AngularJS", # or Angular (Web Framework)
        "docker": "Docker (Software)",
        "git": "Git (Version Control System)",
        "html": "HTML (Hypertext Markup Language)",
        "css": "CSS (Cascading Style Sheets)",
        "javascript": "JavaScript (Programming Language)",
        "python": "Python (Programming Language)",
        "java": "Java (Programming Language)",
        "golang": "Go (Programming Language)",
        "go": "Go (Programming Language)",
        "php": "PHP (Programming Language)",
        "oracle": "Oracle Database",
        "sql": "SQL (Structured Query Language)",
        "sql server": "Microsoft SQL Server",
        "ms sql": "Microsoft SQL Server",
        "cassandra": "Apache Cassandra",
        "clickhouse": "ClickHouse",
        "prometheus": "Prometheus (Software)",
        "splunk": "Splunk (Software)",
        "figma": "Figma (Software)",
        "wpf": "Windows Presentation Foundation (WPF)",
        "winforms": "Windows Forms (WinForms)",
        "uml": "Unified Modeling Language (UML)",
        "nextjs": "Next.js",
        "vuejs": "Vue.js",
        "node.js": "Node.js",
        "nodejs": "Node.js",
        "gcp": "Google Cloud Platform (GCP)",
        "ec2": "Amazon EC2",
        "lambda": "AWS Lambda",
        "event bridge": "Amazon EventBridge",
        "cloudwatch": "Amazon CloudWatch",
        "cloudformation": "AWS CloudFormation",
        "gitlab ci/cd": "GitLab",
        "jenkins": "Jenkins (Software)",
        "autosar": "AUTOSAR",
        "can": "Controller Area Network (CAN)",
        "canoe": "CANoe (Software)",
        "canalyzer": "CANalyzer",
        "iso 26262": "ISO 26262",
        "aspice": "Automotive SPICE (ASPICE)",
        "uds (unified diagnostic services)": "Unified Diagnostic Services (UDS)",
        "toeic 650": "TOEIC",
        "topik level 5": "TOPIK",
        
        # Skill mới (Valid tech/tools/concepts but not in current DB)
        "claude code": "Skill mới",
        "cursor": "Skill mới",
        "cursorai": "Skill mới",
        "github copilot": "Skill mới",
        "github copilot": "Skill mới",
        "ollama": "Skill mới",
        "chatgpt": "Skill mới",
        "rag": "Skill mới",
        "evals": "Skill mới",
        "agent loops": "Skill mới",
        "hallucination detection": "Skill mới",
        "function calling": "Skill mới",
        "mcp": "Skill mới",
        "sotif analysis": "Skill mới",
        "vtest": "Skill mới",
        
        # Rác (Junk/Noise to be rejected by the system)
        "development": "Rác",
        "programming": "Rác",
        "frameworks": "Rác",
        "services": "Rác",
        "coding": "Rác",
        "reviews": "Rác",
        "testing": "Rác",
        "proactive": "Rác",
        "proactive communication": "Rác",
        "mentoring": "Rác",
        "independent work": "Rác",
        "independent research": "Rác",
        "interpersonal skills": "Rác",
        "collaboration skills": "Rác",
        "communication skills": "Rác",
        "driven": "Rác",
        "language": "Rác",
        "oop": "Rác",
        "integration": "Rác",
        "multiple programming languages": "Rác",
        "multiple tech stacks": "Rác",
        "ad industry trends": "Rác",
        "ad technologies": "Rác",
        "operational best practices": "Rác",
        "technology certifications": "Rác",
        "english communication": "Rác",
        "english communications": "Rác",
        "software languages": "Rác",
        "software application implementation": "Rác",
        "programming skills": "Rác",
        "reviews": "Rác"
    }
    
    # Generic lowercase matches to remove
    junk_patterns = [
        r"skills$", r"practices$", r"principles$", r"concepts$", r"patterns$", 
        r"methodologies$", r"best practices", r"framework$"
    ]
    
    normalization_gt = []
    
    matched_db_count = 0
    manual_mapped_count = 0
    new_skills_count = 0
    junk_count = 0
    
    for item in pipe_data:
        url = item.get("url")
        skills = item.get("skills", [])
        
        for s in skills:
            s_clean = s.strip()
            s_lower = s_clean.lower()
            
            normalized = None
            
            # 1. Check manual mapping list
            if s_lower in manual_mappings:
                normalized = manual_mappings[s_lower]
                if normalized == "Rác":
                    junk_count += 1
                elif normalized == "Skill mới":
                    new_skills_count += 1
                else:
                    manual_mapped_count += 1
            # 2. Check exact DB match
            elif s_lower in db_map:
                normalized = db_map[s_lower]
                matched_db_count += 1
            # 3. Apply general rules for Junk
            elif any(s_clean.lower().endswith(p.replace("$", "")) for p in ["principles", "practices", "frameworks", "services", "concepts"]):
                normalized = "Rác"
                junk_count += 1
            # 4. Fallback classification: if it contains generic software words and is long
            elif any(w in s_lower for w in ["development", "programming", "engineering", "skills"]) and len(s_clean.split()) > 2:
                normalized = "Rác"
                junk_count += 1
            # 5. Default fallback: It is a valid technical skill but not in DB
            else:
                normalized = "Skill mới"
                new_skills_count += 1
                
            normalization_gt.append({
                "url": url,
                "skill_extract": s_clean,
                "skill_normalize": normalized
            })
            
    print("=" * 80)
    print("      SCENARIO 2 GROUND TRUTH STATS")
    print("=" * 80)
    print(f"Total entries processed: {len(normalization_gt)}")
    print(f" - Matched DB exactly: {matched_db_count}")
    print(f" - Manually mapped (Tech): {manual_mapped_count}")
    print(f" - New valid skills (Skill mới): {new_skills_count}")
    print(f" - Noise/Junk (Rác): {junk_count}")
    print("=" * 80)
    
    # Save the output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(normalization_gt, f, ensure_ascii=False, indent=2)
    print(f"✓ Successfully saved Ground Truth to: {output_file}")

if __name__ == "__main__":
    main()
