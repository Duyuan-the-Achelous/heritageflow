resource "aws_dynamodb_table" "main" {
  name         = var.project_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = { Name = var.project_name }
}

resource "aws_sqs_queue" "dead_letter" {
  name                        = "${var.project_name}-events-dlq.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600
}

resource "aws_sqs_queue" "events" {
  name                        = "${var.project_name}-events.fifo"
  fifo_queue                  = true
  content_based_deduplication = false
  visibility_timeout_seconds  = 60
  message_retention_seconds   = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 5
  })
}

data "archive_file" "stream_worker" {
  type        = "zip"
  source_file = "${path.module}/../../workers/stream_to_queue.py"
  output_path = "${path.module}/stream_to_queue.zip"
}

resource "aws_lambda_function" "stream_worker" {
  function_name    = "${var.project_name}-stream-to-queue"
  role             = aws_iam_role.stream_worker.arn
  filename         = data.archive_file.stream_worker.output_path
  source_code_hash = data.archive_file.stream_worker.output_base64sha256
  runtime          = "python3.13"
  handler          = "stream_to_queue.handler"
  timeout          = 30

  environment {
    variables = {
      QUEUE_URL = aws_sqs_queue.events.url
    }
  }
}

resource "aws_lambda_event_source_mapping" "dynamodb" {
  event_source_arn  = aws_dynamodb_table.main.stream_arn
  function_name     = aws_lambda_function.stream_worker.arn
  starting_position = "LATEST"
  batch_size        = 50

  filter_criteria {
    filter {
      pattern = jsonencode({
        dynamodb = {
          NewImage = {
            entity_type = { S = ["event"] }
          }
        }
      })
    }
  }
}

