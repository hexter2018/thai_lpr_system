#!/usr/bin/env python3
"""
EasyOCR Fine-tuning Script for Thai License Plates
Active Learning from MLPR corrections

Usage:
    # Export MLPR samples from database
    python train_easyocr.py --export_from_db \
        --db_url "postgresql://lpr:lpr2024@localhost:5432/lpr_v2" \
        --data_dir /storage/retrain_easyocr

    # Train on exported samples
    python train_easyocr.py \
        --data_dir /storage/retrain_easyocr \
        --output_dir /models/easyocr_finetuned \
        --epochs 100 \
        --batch_size 16
"""
import argparse
import json
import logging
import os
import shutil
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


class ThaiPlateDataset(Dataset):
    """
    Dataset for Thai License Plate Recognition Training
    
    Expected structure:
        data_dir/
        ├── images/
        │   ├── mlpr_001.jpg
        │   ├── mlpr_002.jpg
        │   └── ...
        └── labels.json  # {"mlpr_001.jpg": "1กก 1234", ...}
    """
    
    def __init__(
        self,
        data_dir: Path,
        labels_file: Path,
        img_height: int = 64,
        img_width: int = 256,
        max_length: int = 20
    ):
        self.data_dir = data_dir
        self.img_height = img_height
        self.img_width = img_width
        self.max_length = max_length
        
        # Load labels
        with open(labels_file, 'r', encoding='utf-8') as f:
            self.labels = json.load(f)
        
        self.images = list(self.labels.keys())
        
        # Build character vocabulary
        self.chars = self._build_vocab()
        self.char_to_idx = {c: i for i, c in enumerate(self.chars)}
        self.idx_to_char = {i: c for c, i in self.char_to_idx.items()}
        
        log.info("Dataset loaded: %d samples", len(self.images))
        log.info("Vocabulary size: %d characters", len(self.chars))
    
    def _build_vocab(self) -> List[str]:
        """Build character vocabulary from labels"""
        chars = set()
        for label in self.labels.values():
            chars.update(label)
        
        # Thai alphabet + numbers + space
        chars = sorted(list(chars))
        
        # Add special tokens
        vocab = ['<PAD>', '<SOS>', '<EOS>'] + chars
        return vocab
    
    def __len__(self):
        return len(self.images)
    
    def __getitem__(self, idx):
        img_name = self.images[idx]
        img_path = self.data_dir / "images" / img_name
        label = self.labels[img_name]
        
        # Load and preprocess image
        img = Image.open(img_path).convert('L')  # Grayscale
        img = img.resize((self.img_width, self.img_height))
        img = np.array(img, dtype=np.float32) / 255.0
        img = torch.from_numpy(img).unsqueeze(0)  # (1, H, W)
        
        # Encode label
        label_encoded = self._encode_label(label)
        
        return {
            'image': img,
            'label': label_encoded,
            'label_text': label,
            'filename': img_name
        }
    
    def _encode_label(self, text: str) -> torch.Tensor:
        """Encode text label to indices"""
        indices = [self.char_to_idx['<SOS>']]
        for c in text:
            if c in self.char_to_idx:
                indices.append(self.char_to_idx[c])
        indices.append(self.char_to_idx['<EOS>'])
        
        # Pad to max_length
        while len(indices) < self.max_length:
            indices.append(self.char_to_idx['<PAD>'])
        
        return torch.tensor(indices[:self.max_length], dtype=torch.long)
    
    def decode_label(self, indices: torch.Tensor) -> str:
        """Decode indices back to text"""
        chars = []
        for idx in indices:
            idx = int(idx.item())
            if idx == self.char_to_idx['<EOS>']:
                break
            if idx not in [self.char_to_idx['<PAD>'], self.char_to_idx['<SOS>']]:
                chars.append(self.idx_to_char[idx])
        return ''.join(chars)


class SimpleCRNN(nn.Module):
    """
    Simple CRNN model for Thai plate recognition
    (Simplified version for demonstration)
    
    For production, use official EasyOCR model architecture:
    https://github.com/JaidedAI/EasyOCR/tree/master/trainer
    """
    
    def __init__(self, vocab_size: int, hidden_size: int = 256):
        super(SimpleCRNN, self).__init__()
        
        # CNN feature extractor
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 64, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
        )
        
        # RNN sequence model
        self.rnn = nn.LSTM(
            input_size=256 * 8,  # After 3 pooling layers: 64/8 = 8
            hidden_size=hidden_size,
            num_layers=2,
            bidirectional=True,
            batch_first=True
        )
        
        # Output layer
        self.fc = nn.Linear(hidden_size * 2, vocab_size)
    
    def forward(self, x):
        # CNN features
        conv = self.cnn(x)  # (B, 256, 8, W)
        
        # Reshape for RNN
        b, c, h, w = conv.size()
        conv = conv.permute(0, 3, 1, 2)  # (B, W, 256, 8)
        conv = conv.reshape(b, w, -1)    # (B, W, 256*8)
        
        # RNN
        output, _ = self.rnn(conv)  # (B, W, hidden*2)
        
        # Output
        output = self.fc(output)  # (B, W, vocab_size)
        
        return output


class EasyOCRFineTuner:
    """Fine-tune OCR model on Thai license plates"""
    
    def __init__(
        self,
        data_dir: Path,
        output_dir: Path,
        device: str = 'cuda'
    ):
        self.data_dir = data_dir
        self.output_dir = output_dir
        self.device = device
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        log.info("EasyOCR Fine-tuner initialized (device=%s)", device)
    
    def prepare_dataset(self) -> ThaiPlateDataset:
        """Load and prepare training dataset"""
        labels_file = self.data_dir / "labels.json"
        
        if not labels_file.exists():
            raise FileNotFoundError(f"Labels file not found: {labels_file}")
        
        dataset = ThaiPlateDataset(self.data_dir, labels_file)
        return dataset
    
    def train(
        self,
        epochs: int = 100,
        batch_size: int = 16,
        learning_rate: float = 1e-4,
        save_interval: int = 10
    ):
        """Fine-tune OCR model"""
        dataset = self.prepare_dataset()
        
        # Split train/val
        train_size = int(0.9 * len(dataset))
        val_size = len(dataset) - train_size
        train_dataset, val_dataset = torch.utils.data.random_split(
            dataset, [train_size, val_size]
        )
        
        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            num_workers=4
        )
        
        val_loader = DataLoader(
            val_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=2
        )
        
        # Initialize model
        model = SimpleCRNN(
            vocab_size=len(dataset.chars),
            hidden_size=256
        ).to(self.device)
        
        # Loss and optimizer
        criterion = nn.CrossEntropyLoss(ignore_index=dataset.char_to_idx['<PAD>'])
        optimizer = optim.Adam(model.parameters(), lr=learning_rate)
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode='min', factor=0.5, patience=5
        )
        
        log.info("Training: epochs=%d, batch=%d, lr=%.6f", epochs, batch_size, learning_rate)
        log.info("Train samples: %d, Val samples: %d", train_size, val_size)
        
        best_val_loss = float('inf')
        
        for epoch in range(epochs):
            # Train
            model.train()
            train_loss = 0.0
            
            for batch_idx, batch in enumerate(train_loader):
                images = batch['image'].to(self.device)
                labels = batch['label'].to(self.device)
                
                optimizer.zero_grad()
                
                # Forward
                outputs = model(images)  # (B, W, vocab_size)
                
                # Reshape for loss
                outputs = outputs.permute(0, 2, 1)  # (B, vocab_size, W)
                
                # Loss
                loss = criterion(outputs, labels)
                
                # Backward
                loss.backward()
                optimizer.step()
                
                train_loss += loss.item()
                
                if (batch_idx + 1) % 10 == 0:
                    log.info(
                        "Epoch %d/%d, Batch %d/%d, Loss: %.4f",
                        epoch + 1, epochs, batch_idx + 1, len(train_loader), loss.item()
                    )
            
            train_loss /= len(train_loader)
            
            # Validation
            model.eval()
            val_loss = 0.0
            correct = 0
            total = 0
            
            with torch.no_grad():
                for batch in val_loader:
                    images = batch['image'].to(self.device)
                    labels = batch['label'].to(self.device)
                    
                    outputs = model(images)
                    outputs_t = outputs.permute(0, 2, 1)
                    
                    loss = criterion(outputs_t, labels)
                    val_loss += loss.item()
                    
                    # Accuracy
                    preds = outputs.argmax(dim=2)
                    for i in range(preds.size(0)):
                        pred_text = dataset.dataset.decode_label(preds[i])
                        true_text = batch['label_text'][i]
                        if pred_text == true_text:
                            correct += 1
                        total += 1
            
            val_loss /= len(val_loader)
            accuracy = 100.0 * correct / total if total > 0 else 0.0
            
            log.info(
                "Epoch %d/%d - Train Loss: %.4f, Val Loss: %.4f, Accuracy: %.2f%%",
                epoch + 1, epochs, train_loss, val_loss, accuracy
            )
            
            # Learning rate schedule
            scheduler.step(val_loss)
            
            # Save checkpoint
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                checkpoint_path = self.output_dir / "best_model.pth"
                torch.save({
                    'epoch': epoch,
                    'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'val_loss': val_loss,
                    'accuracy': accuracy,
                    'vocab': dataset.chars,
                }, checkpoint_path)
                log.info("✓ Saved best model (val_loss=%.4f)", val_loss)
            
            if (epoch + 1) % save_interval == 0:
                checkpoint_path = self.output_dir / f"checkpoint_epoch_{epoch+1}.pth"
                torch.save({
                    'epoch': epoch,
                    'model_state_dict': model.state_dict(),
                    'optimizer_state_dict': optimizer.state_dict(),
                    'val_loss': val_loss,
                }, checkpoint_path)
                log.info("Checkpoint saved: %s", checkpoint_path)
        
        log.info("Training complete! Best model saved to: %s", self.output_dir / "best_model.pth")


def export_mlpr_samples(
    db_connection_string: str,
    output_dir: Path,
    limit: int = 1000
) -> int:
    """
    Export MLPR samples from database for training
    
    Args:
        db_connection_string: Database URL
        output_dir: Output directory for training data
        limit: Maximum samples to export
    
    Returns:
        Number of samples exported
    """
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        log.error("SQLAlchemy not installed. Run: pip install sqlalchemy")
        return 0
    
    engine = create_engine(db_connection_string)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    labels = {}
    exported_count = 0
    
    log.info("Exporting MLPR samples from database...")
    
    try:
        with engine.connect() as conn:
            # Fetch non-exported MLPR samples
            result = conn.execute(text("""
                SELECT id, crop_path, corrected_text, corrected_province
                FROM mlpr_samples
                WHERE exported = false
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"limit": limit})
            
            rows = result.fetchall()
            
            if not rows:
                log.warning("No MLPR samples to export")
                return 0
            
            for row in rows:
                sample_id = row[0]
                crop_path = Path(row[1])
                text = row[2]
                province = row[3]
                
                if not crop_path.exists():
                    log.warning("Crop not found: %s", crop_path)
                    continue
                
                # Copy image
                dst_name = f"mlpr_{sample_id}{crop_path.suffix}"
                dst_path = images_dir / dst_name
                
                try:
                    shutil.copy2(crop_path, dst_path)
                    
                    # Store label (plate text with province)
                    label = f"{text} {province}".strip() if province else text
                    labels[dst_name] = label
                    
                    exported_count += 1
                except Exception as e:
                    log.error("Failed to copy %s: %s", crop_path, e)
            
            # Mark as exported
            if exported_count > 0:
                sample_ids = [int(row[0]) for row in rows]
                conn.execute(text("""
                    UPDATE mlpr_samples
                    SET exported = true, exported_at = :now
                    WHERE id = ANY(:ids)
                """), {
                    "ids": sample_ids,
                    "now": datetime.utcnow()
                })
                conn.commit()
        
        # Save labels
        labels_file = output_dir / "labels.json"
        with open(labels_file, 'w', encoding='utf-8') as f:
            json.dump(labels, f, ensure_ascii=False, indent=2)
        
        log.info("✓ Exported %d samples to %s", exported_count, output_dir)
        log.info("✓ Labels saved to %s", labels_file)
        
        return exported_count
        
    except Exception as e:
        log.error("Export failed: %s", e)
        return 0
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune EasyOCR for Thai license plates",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--data_dir',
        type=Path,
        required=True,
        help="Training data directory containing images/ and labels.json"
    )
    parser.add_argument(
        '--output_dir',
        type=Path,
        default=Path('/models/easyocr_finetuned'),
        help="Output directory for trained models"
    )
    parser.add_argument(
        '--epochs',
        type=int,
        default=100,
        help="Number of training epochs"
    )
    parser.add_argument(
        '--batch_size',
        type=int,
        default=16,
        help="Training batch size"
    )
    parser.add_argument(
        '--learning_rate',
        type=float,
        default=1e-4,
        help="Learning rate"
    )
    parser.add_argument(
        '--device',
        type=str,
        default='cuda',
        choices=['cuda', 'cpu'],
        help="Device for training"
    )
    parser.add_argument(
        '--export_from_db',
        action='store_true',
        help="Export MLPR samples from database before training"
    )
    parser.add_argument(
        '--db_url',
        type=str,
        help="Database connection string (required with --export_from_db)"
    )
    parser.add_argument(
        '--export_limit',
        type=int,
        default=1000,
        help="Maximum samples to export from database"
    )
    
    args = parser.parse_args()
    
    # Export from database if requested
    if args.export_from_db:
        if not args.db_url:
            log.error("--db_url required when using --export_from_db")
            return 1
        
        count = export_mlpr_samples(args.db_url, args.data_dir, args.export_limit)
        
        if count == 0:
            log.warning("No samples exported. Nothing to train.")
            return 0
    
    # Verify data directory
    if not args.data_dir.exists():
        log.error("Data directory not found: %s", args.data_dir)
        return 1
    
    if not (args.data_dir / "labels.json").exists():
        log.error("labels.json not found in %s", args.data_dir)
        return 1
    
    # Train model
    trainer = EasyOCRFineTuner(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        device=args.device
    )
    
    try:
        trainer.train(
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate
        )
        return 0
    except KeyboardInterrupt:
        log.info("Training interrupted by user")
        return 130
    except Exception as e:
        log.error("Training failed: %s", e, exc_info=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
